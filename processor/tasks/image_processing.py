import io
import time
from datetime import datetime, timezone

import requests
from celery import shared_task

from PIL import Image
from rembg import remove

from shared.config import settings
from shared.database import db
from shared.models import ImageProcessingJob, ProcessingStatus, User
from shared.s3_client import s3_client


@shared_task(bind=True, name="processor.tasks.image_processing.process_image")
def process_image(self, job_id: str, options: dict):
    """Process image based on job options"""
    start_time = time.time()

    with db.sync_session() as session:
        try:
            job = session.get(ImageProcessingJob, job_id)
            if not job:
                raise ValueError(f"Job {job_id} not found")

            _update_job_status(session, job, ProcessingStatus.PROCESSING)

            # Download original from S3
            original_data = _download_from_s3(job.original_file_key)

            # Process image
            processed_data = _process_image_data(original_data, options)

            # Upload result to S3
            processed_key = _upload_to_s3(job, processed_data, options)

            # Update job with results
            _complete_job(session, job, processed_key, start_time)

            # Send result to user
            _send_result_to_user(session, job, processed_data, options)

        except Exception as e:
            _handle_job_failure(session, job_id, e)
            raise


def _download_from_s3(file_key: str) -> bytes:
    """Download file from S3 synchronously"""
    import asyncio

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(s3_client.download_file(file_key))
    finally:
        loop.close()


def _upload_to_s3(job: ImageProcessingJob, data: bytes, options: dict) -> str:
    """Upload file to S3 synchronously"""
    import asyncio

    extension = _get_file_extension(options)
    content_type = _get_content_type(options)
    processed_key = f"processed/{job.user_id}/{job.id}{extension}"

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(
            s3_client.upload_file(data, processed_key, content_type)
        )
    finally:
        loop.close()

    return processed_key


def _process_image_data(image_data: bytes, options: dict) -> bytes:
    """Core image processing logic"""
    img = Image.open(io.BytesIO(image_data))

    remove_bg = options.get("remove_bg", False)
    as_sticker = options.get("as_sticker", False)

    # Remove background if requested
    if remove_bg:
        img = remove(img)

    # Convert to sticker format if requested
    if as_sticker:
        img = _convert_to_sticker(img)
        # Save as WebP for stickers
        output_buffer = io.BytesIO()
        img.save(output_buffer, format="WEBP", quality=95)
        return output_buffer.getvalue()

    # Save as PNG for regular images
    output_buffer = io.BytesIO()
    img.save(output_buffer, format="PNG")
    return output_buffer.getvalue()


def _convert_to_sticker(img: Image.Image) -> Image.Image:
    """Convert image to Telegram sticker format (512x512 max, WebP)"""
    # Telegram stickers: max 512x512, one side must be exactly 512px
    max_size = 512

    # Calculate new dimensions maintaining aspect ratio
    width, height = img.size
    if width > height:
        new_width = max_size
        new_height = int((height / width) * max_size)
    else:
        new_height = max_size
        new_width = int((width / height) * max_size)

    # Resize image
    img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)

    # Ensure RGBA for transparency support
    if img.mode != "RGBA":
        img = img.convert("RGBA")

    return img


def _get_file_extension(options: dict) -> str:
    """Get file extension based on processing options"""
    as_sticker = options.get("as_sticker", False)
    return ".webp" if as_sticker else ".png"


def _get_content_type(options: dict) -> str:
    """Get MIME type based on processing options"""
    as_sticker = options.get("as_sticker", False)
    return "image/webp" if as_sticker else "image/png"


def _update_job_status(session, job: ImageProcessingJob, status: ProcessingStatus):
    """Update job status"""
    job.status = status
    job.updated_at = datetime.now(timezone.utc)
    session.commit()


def _complete_job(session, job: ImageProcessingJob, processed_key: str, start_time: float):
    """Mark job as completed"""
    job.processed_file_key = processed_key
    job.status = ProcessingStatus.COMPLETED
    job.processing_time_seconds = int(time.time() - start_time)
    job.updated_at = datetime.now(timezone.utc)
    session.commit()


def _handle_job_failure(session, job_id: str, error: Exception):
    """Handle job failure"""
    session.rollback()
    job = session.get(ImageProcessingJob, job_id)
    if job:
        job.status = ProcessingStatus.FAILED
        job.error_message = str(error)[:500]
        job.updated_at = datetime.now(timezone.utc)
        session.commit()


def _send_result_to_user(session, job: ImageProcessingJob, image_data: bytes, options: dict):
    """Send processed image back to user via Telegram Bot API"""
    import requests

    bot_token = settings.bot_token.get_secret_value()
    user = session.get(User, job.user_id)

    if not user:
        raise ValueError(f"User {job.user_id} not found")

    as_sticker = options.get("as_sticker", False)

    if as_sticker:
        _send_as_sticker(bot_token, user.telegram_id, image_data, job.id)
    else:
        _send_as_document(bot_token, user.telegram_id, image_data, job.id)


def _send_as_document(bot_token: str, telegram_id: int, image_data: bytes, job_id):
    """Send result as document"""
    url = f"https://api.telegram.org/bot{bot_token}/sendDocument"

    files = {'document': (f"result_{job_id}.png", image_data, "image/png")}
    data = {
        'chat_id': str(telegram_id),
        'caption': f"✅ Processing complete!\nJob ID: {job_id}"
    }

    response = requests.post(url, files=files, data=data)
    if response.status_code != 200:
        raise ValueError(f"Failed to send document: {response.text}")


def _send_as_sticker(bot_token: str, telegram_id: int, image_data: bytes, job_id):
    """Send result as sticker using Telegram's sendSticker API"""
    url = f"https://api.telegram.org/bot{bot_token}/sendSticker"

    # Telegram stickers need to be sent as 'sticker' field, not 'document'
    files = {'sticker': (f"sticker_{job_id}.webp", image_data, "image/webp")}
    data = {
        'chat_id': str(telegram_id),
    }

    response = requests.post(url, files=files, data=data)

    if response.status_code != 200:
        raise ValueError(f"Failed to send sticker: {response.text}")

    # Send a follow-up message with job info since stickers can't have captions
    url_message = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    message_data = {
        'chat_id': str(telegram_id),
        'text': f"✅ Sticker ready!\nJob ID: {job_id}"
    }
    requests.post(url_message, data=message_data)