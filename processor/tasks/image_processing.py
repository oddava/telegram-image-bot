import io
import time
from datetime import datetime, timezone
from celery import shared_task

from PIL import Image
from rembg import remove

from shared.config import settings
from shared.models import ImageProcessingJob, ProcessingStatus, User
from shared.s3_client import s3_client

# Import synchronous SQLAlchemy
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Create sync engine for Celery tasks
sync_database_url = settings.database_url.replace('postgresql+asyncpg://', 'postgresql+psycopg2://')
sync_engine = create_engine(sync_database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=sync_engine)


@shared_task(bind=True, name="processor.tasks.image_processing.process_image")
def process_image(self, job_id: str, options: dict):
    """Process image based on job options"""
    start_time = time.time()

    session = SessionLocal()
    try:
        # Get job
        job = session.get(ImageProcessingJob, job_id)
        if not job:
            raise ValueError(f"Job {job_id} not found")

        # Update status
        job.status = ProcessingStatus.PROCESSING
        job.updated_at = datetime.now(timezone.utc)
        session.commit()

        # Download original from S3 (synchronous)
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            original_data = loop.run_until_complete(s3_client.download_file(job.original_file_key))
        finally:
            loop.close()

        # Process based on action
        action = options.get("action", "remove_background")
        processed_data = _process_image(original_data, action, options)

        # Upload processed image (synchronous)
        extension = _get_extension(options)
        processed_key = f"processed/{job.user_id}/{job.id}{extension}"

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(
                s3_client.upload_file(processed_data, processed_key, f"image/{extension.lstrip('.')}")
            )
        finally:
            loop.close()

        # Update job
        job.processed_file_key = processed_key
        job.status = ProcessingStatus.COMPLETED
        job.processing_time_seconds = int(time.time() - start_time)
        job.updated_at = datetime.now(timezone.utc)
        session.commit()

        # Send result to user
        _send_result_to_user(session, job, processed_data)

    except Exception as e:
        session.rollback()
        job = session.get(ImageProcessingJob, job_id)
        if job:
            job.status = ProcessingStatus.FAILED
            job.error_message = str(e)[:500]
            job.updated_at = datetime.now(timezone.utc)
            session.commit()
        raise
    finally:
        session.close()


def _process_image(image_data: bytes, action: str, options: dict) -> bytes:
    """Core image processing logic"""
    img = Image.open(io.BytesIO(image_data))

    if action == "remove_background":
        output = remove(img)
        output_buffer = io.BytesIO()
        output.save(output_buffer, format="PNG")
        return output_buffer.getvalue()

    elif action == "resize":
        width = options.get("width", 512)
        height = options.get("height", 512)
        resized = img.resize((width, height), Image.Resampling.LANCZOS)
        output_buffer = io.BytesIO()
        format = img.format or "JPEG"
        resized.save(output_buffer, format=format)
        return output_buffer.getvalue()

    elif action == "format_conversion":
        target_format = options.get("target_format", "png")
        output_buffer = io.BytesIO()

        if target_format.lower() == "jpg" or target_format.lower() == "jpeg":
            target_format = "JPEG"
            if img.mode in ("RGBA", "LA", "P"):
                background = Image.new("RGB", img.size, (255, 255, 255))
                if img.mode == "RGBA":
                    background.paste(img, mask=img.split()[-1])
                else:
                    background.paste(img)
                img = background

        img.save(output_buffer, format=target_format.upper())
        return output_buffer.getvalue()

    return image_data


def _get_extension(options: dict) -> str:
    action = options.get("action", "")
    if action == "remove_background":
        return ".png"
    elif action == "format_conversion":  # ✅ Changed
        fmt = options.get("target_format", "png")
        return f".{fmt.lower()}"
    return ".png"

def _send_result_to_user(session, job: ImageProcessingJob, image_data: bytes):
    """Send processed image back to user via Telegram Bot API"""
    import requests

    bot_token = settings.bot_token
    url = f"https://api.telegram.org/bot{bot_token}/sendPhoto"

    # Get user's telegram_id
    user = session.get(User, job.user_id)
    if not user:
        raise ValueError(f"User {job.user_id} not found")

    files = {'photo': (f"result_{job.id}.png", image_data, 'image/png')}
    data = {
        'chat_id': str(user.telegram_id),
        'caption': f"✅ Processing complete!\nJob ID: {job.id}"
    }

    response = requests.post(url, files=files, data=data)
    if response.status_code != 200:
        raise ValueError(f"Failed to send photo: {response.text}")