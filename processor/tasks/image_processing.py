import io
import time
from datetime import datetime, timezone
from celery import shared_task

from PIL import Image
from rembg import remove

from shared.config import settings
from shared.database import get_async_session
from shared.models import ImageProcessingJob, ProcessingStatus
from shared.s3_client import s3_client


@shared_task(bind=True, name="processor.tasks.image_processing.process_image")
def process_image(self, job_id: str, options: dict):
    """Process image based on job options"""
    start_time = time.time()

    async def run_async():
        async for session in get_async_session():
            job = await session.get(ImageProcessingJob, job_id)
            if not job:
                raise ValueError(f"Job {job_id} not found")

            try:
                job.status = ProcessingStatus.PROCESSING
                job.updated_at = datetime.now(timezone.utc)
                await session.commit()

                # Download original from S3
                original_data = await s3_client.download_file(job.original_file_key)

                # Process based on action
                action = options.get("action", "remove_background")
                processed_data = await _process_image(original_data, action, options)

                # Upload processed image
                extension = _get_extension(options)
                processed_key = f"processed/{job.user_id}/{job.id}{extension}"
                await s3_client.upload_file(
                    processed_data, processed_key, f"image/{extension.lstrip('.')}"
                )

                # Update job
                job.processed_file_key = processed_key
                job.status = ProcessingStatus.COMPLETED
                job.processing_time_seconds = int(time.time() - start_time)
                job.updated_at = datetime.now(timezone.utc)
                await session.commit()

                # Send result to user (via Telegram Bot API)
                await _send_result_to_user(job, processed_data)

            except Exception as e:
                job.status = ProcessingStatus.FAILED
                job.error_message = str(e)[:500]
                job.updated_at = datetime.now(timezone.utc)
                await session.commit()
                raise

    import asyncio
    asyncio.run(run_async())


async def _process_image(image_data: bytes, action: str, options: dict) -> bytes:
    """Core image processing logic"""
    img = Image.open(io.BytesIO(image_data))

    if action == "remove_background":
        # Use rembg for background removal
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

    elif action.startswith("format:"):
        target_format = options.get("target_format", "png")
        output_buffer = io.BytesIO()

        if target_format.lower() == "jpg":
            target_format = "JPEG"
            if img.mode in ("RGBA", "LA"):
                background = Image.new("RGB", img.size, (255, 255, 255))
                if img.mode == "RGBA":
                    background.paste(img, mask=img.split()[-1])
                img = background

        img.save(output_buffer, format=target_format.upper())
        return output_buffer.getvalue()

    return image_data  # Default: return original


def _get_extension(options: dict) -> str:
    action = options.get("action", "")
    if action == "remove_background":
        return ".png"
    elif action.startswith("format:"):
        fmt = options.get("target_format", "png")
        return f".{fmt}"
    return ".png"


async def _send_result_to_user(job: ImageProcessingJob, image_data: bytes):
    """Send processed image back to user via Telegram Bot API"""
    import aiohttp

    bot_token = settings.bot_token
    url = f"https://api.telegram.org/bot{bot_token}/sendPhoto"

    # In production, use proper bot API call with file upload
    # For brevity, this is a simplified version
    data = aiohttp.FormData()
    data.add_field("chat_id", job.user_id)
    data.add_field("photo", image_data, filename=f"result_{job.id}.png")
    data.add_field("caption", f"✅ Processing complete!\nJob ID: {job.id}")

    async with aiohttp.ClientSession() as session:
        await session.post(url, data=data)