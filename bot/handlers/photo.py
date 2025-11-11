import logging
import uuid
from datetime import datetime, timezone
from io import BytesIO

from aiogram import Router, F, Bot
from aiogram.types import BufferedInputFile, Message, File, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.i18n import gettext as _
from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession

from shared.config import settings
from shared.models import User, ImageProcessingJob, ProcessingStatus
from shared.s3_client import s3_client

router = Router(name="photo")
router.message.filter(F.photo | F.document)

logger = logging.getLogger(__name__)

async def download_telegram_file(file: File, bot: Bot) -> bytes:
    maybe_buffer = await bot.download(file.file_id)
    if maybe_buffer is None:
        raise RuntimeError("Download failed, got None instead of BytesIO.")
    assert isinstance(maybe_buffer, BytesIO)
    return maybe_buffer.getvalue()


@router.message(F.photo)
async def handle_photo(
        message: Message,
        bot: Bot,
        user: User,
        session: AsyncSession,
):
    """Handle photo messages"""
    # Quota already checked by middleware

    photo = message.photo[-1]  # Get highest quality

    if photo.file_size > settings.max_file_size_bytes:
        return await message.answer(
            _("❌ File too large! Max size: {size} MB").format(
                size=settings.max_file_size_mb
            )
        )

    await message.answer(_("📥 Downloading image..."))
    file_info = await bot.get_file(photo.file_id)
    image_data = await download_telegram_file(file_info, bot)

    logger.info(f"Downloaded image: {len(image_data)} bytes")

    # Store original to S3
    original_key = f"original/{user.telegram_id}/{uuid.uuid4()}.jpg"

    try:
        logger.info(f"Uploading to S3: {original_key}")
        upload_url = await s3_client.upload_file(image_data, original_key, "image/jpeg")
        logger.info(f"✅ Successfully uploaded to S3: {upload_url}")
    except Exception as e:
        logger.error(f"❌ S3 Upload failed: {e}", exc_info=True)
        return await message.answer(f"❌ Failed to upload image: {str(e)}")

    # Create processing job
    job = ImageProcessingJob(
        id=uuid.uuid4(),
        user_id=user.id,
        original_filename=f"photo_{photo.file_id}.jpg",
        original_file_key=original_key,
        status=ProcessingStatus.PENDING,
        processing_options='{"action": "remove_background"}',
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    session.add(job)
    await session.commit()

    logger.info(f"Created job {job.id} for file {original_key}")

    # Show processing options
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🖼️ Remove Background",
                    callback_data=f"process:bg:{job.id}"
                ),
                InlineKeyboardButton(
                    text="🔄 Convert Format",
                    callback_data=f"process:convert:{job.id}"
                ),
            ],
            [
                InlineKeyboardButton(
                    text="📐 Resize",
                    callback_data=f"process:resize:{job.id}"
                ),
                InlineKeyboardButton(
                    text="📦 Batch",
                    callback_data=f"process:batch:{job.id}"
                ),
            ],
        ]
    )

    await message.answer_photo(
        photo=BufferedInputFile(image_data, filename="preview.jpg"),
        caption=_("Choose processing option:"),
        reply_markup=keyboard,
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

    if document.file_size > settings.max_file_size_bytes:
        return await message.answer(
            _("❌ File too large! Max size: {size} MB").format(
                size=settings.max_file_size_mb
            )
        )

    await message.answer(_("📥 Downloading document..."))
    file_info = await bot.get_file(document.file_id)
    image_data = await download_telegram_file(file_info, bot)

    # Store original to S3
    original_key = f"original/{user.telegram_id}/{uuid.uuid4()}.jpg"
    try:
        upload_url = await s3_client.upload_file(image_data, original_key, "image/jpeg")
        print(f"✅ Uploaded to S3: {upload_url}")
    except Exception as e:
        print(f"❌ S3 Upload failed: {e}")
        return await message.answer(f"❌ Failed to upload image: {str(e)}")

    # Create processing job
    job = ImageProcessingJob(
        id=uuid.uuid4(),
        user_id=user.id,
        original_filename=document.file_name,
        original_file_key=original_key,
        status=ProcessingStatus.PENDING,
        processing_options='{"action": "remove_background"}',
        created_at=func.now(),
        updated_at=func.now(),
    )
    session.add(job)
    await session.commit()

    await message.answer(
        _("✅ Document received! Use /history to process it.\nJob ID: {job_id}").format(
            job_id=job.id
        )
    )