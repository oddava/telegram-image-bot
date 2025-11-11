from celery import Celery
from shared.config import settings

# Initialize Celery app
celery_app = Celery("bot_publisher")
celery_app.conf.update(
    broker_url=settings.celery_broker_url,
    result_backend=settings.celery_result_backend,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
)


async def publish_processing_task(job_id: str, options: dict) -> None:
    """
    Publish image processing task to Celery queue
    """
    celery_app.send_task(
        "processor.tasks.image_processing.process_image",
        args=[job_id, options],
        queue="image_processing",
        routing_key="image.process",
    )