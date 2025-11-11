import io
import time
from datetime import datetime
from celery import shared_task
import asyncio
import uuid

from PIL import Image
from rembg import remove

from shared.config import settings
from shared.database import async_session_maker
from shared.models import ImageProcessingJob, ProcessingStatus
from shared.s3_client import s3_client


@shared_task(bind=True, name="processor.tasks.image_processing.process_image")
def process_image(self, job_id: str, options: dict):
    """Process image based on job options (Celery wrapper)."""
    start_time = time.time()

    async def run_async():
        # Use async session maker directly
        async with async_session_maker() as session:
            # If your job_id column is UUID, you may need to convert:
            try:
                # If stored as UUID in DB and job_id is string:
                job_pk = uuid.UUID(job_id)
            except Exception:
                job_pk = job_id  # fallback

            job = await session.get(ImageProcessingJob, job_pk)
            if not job:
                raise ValueError(f"Job {job_id} not found")

            try:
                job.status = ProcessingStatus.PROCESSING
                job.updated_at = datetime.utcnow()
                await session.commit()

                # Download original from S3 (async wrapper)
                original_data = await s3_client.download_file(job.original_file_key)

                # Process
                processed_data = await _process_image(original_data, options.get("action", "remove_background"), options)

                # Upload processed image (async wrapper)
                extension = _get_extension(options)
                processed_key = f"processed/{job.user_id}/{job.id}{extension}"
                await s3_client.upload_file(processed_data, processed_key, content_type=f"image/{extension.lstrip('.')}")

                # Update job
                job.processed_file_key = processed_key
                job.status = ProcessingStatus.COMPLETED
                job.processing_time_seconds = int(time.time() - start_time)
                job.updated_at = datetime.utcnow()
                await session.commit()

                # Send result (async)
                await _send_result_to_user(job, processed_data)

            except Exception as exc:
                # try to record failure; swallow errors in DB ops if necessary
                try:
                    job.status = ProcessingStatus.FAILED
                    job.error_message = str(exc)[:500]
                    job.updated_at = datetime.utcnow()
                    await session.commit()
                except Exception:
                    await session.rollback()
                raise

    asyncio.run(run_async())


async def _process_image(image_data: bytes, action: str, options: dict) -> bytes:
    img = Image.open(io.BytesIO(image_data)).convert("RGBA")

    if action == "remove_background":
        output = remove(img)
        output_buffer = io.BytesIO()
        output.save(output_buffer, format="PNG")
        return output_buffer.getvalue()

    if action == "resize":
        width = int(options.get("width", 512))
        height = int(options.get("height", 512))
        resized = img.resize((width, height), Image.Resampling.LANCZOS)
        output_buffer = io.BytesIO()
        fmt = img.format or "JPEG"
        resized.save(output_buffer, format=fmt)
        return output_buffer.getvalue()

    if action.startswith("format:") or options.get("action") == "format":
        target_format = options.get("target_format", "png").upper()
        output_buffer = io.BytesIO()
        if target_format in ("JPG", "JPEG") and img.mode in ("RGBA", "LA"):
            background = Image.new("RGB", img.size, (255, 255, 255))
            background.paste(img, mask=img.split()[-1])
            img = background
        img.save(output_buffer, format=target_format)
        return output_buffer.getvalue()

    return image_data


def _get_extension(options: dict) -> str:
    action = options.get("action", "")
    if action == "remove_background":
        return ".png"
    elif action.startswith("format:") or options.get("target_format"):
        fmt = options.get("target_format", "png")
        return f".{fmt.lower()}"
    return ".png"


async def _send_result_to_user(job: ImageProcessingJob, image_data: bytes):
    """Send processed image back to user; ensure chat_id is a telegram id, not DB pk."""
    import aiohttp

    bot_token = settings.bot_token
    url = f"https://api.telegram.org/bot{bot_token}/sendPhoto"

    # Ensure we send to the telegram_id (not the DB user id)
    chat_id = getattr(job, "telegram_user_id", None) or getattr(job, "telegram_id", None)
    # if job.user is relationship you might do: job.user.telegram_id

    if chat_id is None:
        # fallback: don't attempt to send
        return

    data = aiohttp.FormData()
    data.add_field("chat_id", str(chat_id))
    data.add_field("photo", image_data, filename=f"result_{job.id}.png", content_type="image/png")
    data.add_field("caption", f"✅ Processing complete!\nJob ID: {job.id}")

    async with aiohttp.ClientSession() as session:
        async with session.post(url, data=data) as resp:
            # optionally check resp.status and log
            pass
