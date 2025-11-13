import asyncio
import time
import uuid
from datetime import datetime, timezone
from io import BytesIO
from typing import Optional

from aiogram import Router, F, Bot
from aiogram.types import BufferedInputFile, Message, File, InlineKeyboardMarkup, InlineKeyboardButton

from sqlalchemy.ext.asyncio import AsyncSession

from shared.config import settings
from shared.models import User, ImageProcessingJob, ProcessingStatus
from shared.s3_client import s3_client
from loguru import logger
from aiogram.utils.i18n import gettext as _

router = Router(name="photo")
router.message.filter(F.photo | F.document)

# Track media groups to avoid duplicate messages
media_group_tracker = {}  # {media_group_id: (timestamp, job_count)}


async def download_telegram_file(file: File, bot: Bot) -> bytes:
    """Download file from Telegram servers"""
    maybe_buffer = await bot.download(file.file_id)
    if maybe_buffer is None:
        raise RuntimeError("Download failed, got None instead of BytesIO.")
    assert isinstance(maybe_buffer, BytesIO)
    return maybe_buffer.getvalue()


def create_processing_keyboard(job_id: uuid.UUID) -> InlineKeyboardMarkup:
    """Create inline keyboard for processing options"""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🖼️ Remove BG",
                    callback_data=f"toggle:bg:{job_id}"
                ),
                InlineKeyboardButton(
                    text="🎨 As Sticker",
                    callback_data=f"toggle:sticker:{job_id}"
                ),
            ],
            [
                InlineKeyboardButton(
                    text="▶️ Process",
                    callback_data=f"process:start:{job_id}"
                ),
            ],
        ]
    )


async def upload_to_s3(image_data: bytes, key: str, content_type: str = "image/jpeg") -> str:
    """Upload image to S3 with error handling"""
    try:
        logger.info(f"Uploading to S3: {key}")
        upload_url = await s3_client.upload_file(image_data, key, content_type)
        logger.info(f"✅ Successfully uploaded to S3: {upload_url}")
        return upload_url
    except Exception as e:
        logger.error(f"❌ S3 Upload failed: {e}", exc_info=True)
        raise


async def create_processing_job(
        session: AsyncSession,
        user: User,
        original_filename: str,
        original_key: str,
) -> ImageProcessingJob:
    """Create a new image processing job"""
    job = ImageProcessingJob(
        id=uuid.uuid4(),
        user_id=user.id,
        original_filename=original_filename,
        original_file_key=original_key,
        status=ProcessingStatus.PENDING,
        processing_options='{"remove_bg": false, "as_sticker": false}',
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    session.add(job)
    await session.commit()
    logger.info(f"Created job {job.id} for file {original_key}")
    return job


async def check_file_size(message: Message, file_size: int) -> bool:
    """Check if file size is within limits"""
    if file_size > settings.max_file_size_bytes:
        await message.answer(
            _("❌ File too large! Max size: {size} MB").format(
                size=settings.max_file_size_mb
            )
        )
        return False
    return True


async def handle_image_upload(
        message: Message,
        bot: Bot,
        user: User,
        session: AsyncSession,
        file_id: str,
        file_size: int,
        filename: str,
        media_group_id: str = None,
) -> Optional[ImageProcessingJob]:
    """Common logic for handling image uploads"""
    from aiogram.utils.i18n import gettext as _

    # Check file size
    if not await check_file_size(message, file_size):
        return None

    # Track media groups and determine if this is the first image
    is_first_in_group = False
    if media_group_id:
        current_time = time.time()

        # Initialize or update tracker
        if media_group_id not in media_group_tracker:
            media_group_tracker[media_group_id] = {
                'count': 0,
                'timestamp': current_time
            }
            is_first_in_group = True

        tracker = media_group_tracker[media_group_id]
        tracker['count'] += 1
        tracker['timestamp'] = current_time

        # Clean up old entries (older than 5 seconds)
        to_remove = [k for k, v in media_group_tracker.items()
                     if current_time - v['timestamp'] > 5]
        for k in to_remove:
            del media_group_tracker[k]

    # Only show download status for single images or first album image
    download_msg = None
    if not media_group_id or is_first_in_group:
        status_text = _("📥 Downloading album...") if media_group_id else _("📥 Downloading image...")
        download_msg = await message.answer(status_text)

    try:
        # Download image
        file_info = await bot.get_file(file_id)
        image_data = await download_telegram_file(file_info, bot)
        logger.info(f"Downloaded image: {len(image_data)} bytes")

        # Generate S3 key
        original_key = f"original/{user.telegram_id}/{uuid.uuid4()}.jpg"

        # Upload to S3
        await upload_to_s3(image_data, original_key)

        # Create processing job
        job = await create_processing_job(session, user, filename, original_key)

        # Handle messaging based on album/single image
        if media_group_id:
            # Only send album message for the first image
            if is_first_in_group:
                # Wait briefly to collect most images
                await asyncio.sleep(0.5)
                count = media_group_tracker[media_group_id]['count']

                if download_msg:
                    await download_msg.delete()

                await message.answer(
                    _("📸 Album detected! Processing {count} images...\n"
                      "Use /history to process them all at once.").format(count=count))
            return None
        else:
            # Single image - show interactive preview
            keyboard = create_processing_keyboard(job.id)
            await message.answer_photo(
                photo=BufferedInputFile(image_data, filename="preview.jpg"),
                caption=_("🎨 Choose processing options (toggle buttons, then press Process):"),
                reply_markup=keyboard,
            )
            return job

    except Exception as e:
        # Clean up on error
        if download_msg:
            await download_msg.delete()
        return await message.answer(f"❌ Failed to process image: {str(e)}")

    finally:
        # Always clean up download message for single images
        if download_msg and not media_group_id:
            try:
                await download_msg.delete()
            except Exception:
                pass


@router.message(F.photo)
async def handle_photo(
        message: Message,
        bot: Bot,
        user: User,
        session: AsyncSession,
):
    """Handle photo messages"""
    photo = message.photo[-1]

    await handle_image_upload(
        message=message,
        bot=bot,
        user=user,
        session=session,
        file_id=photo.file_id,
        file_size=photo.file_size,
        filename=f"photo_{photo.file_id}.jpg",
        media_group_id=message.media_group_id,
    )


@router.message(F.document & F.document.mime_type.startswith("image/"))
async def handle_document(
        message: Message,
        bot: Bot,
        user: User,
        session: AsyncSession,
):
    """Handle document messages"""
    document = message.document

    await handle_image_upload(
        message=message,
        bot=bot,
        user=user,
        session=session,
        file_id=document.file_id,
        file_size=document.file_size,
        filename=document.file_name or f"document_{document.file_id}.jpg",
        media_group_id=message.media_group_id,
    )
