import asyncio
import os
from celery import Celery
from shared.config import settings
from shared.database import db


asyncio.run(db.init(settings.DATABASE_URL.get_secret_value()))

# Configure Celery
celery_app = Celery("processor")
celery_app.conf.update(
    broker_connection_retry_on_startup=True,
    broker_url=settings.celery_broker_url,
    result_backend=settings.celery_result_backend,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_track_started=True,
    task_time_limit=300,
    task_soft_time_limit=270,
    imports=[
        "processor.tasks.image_processing",
    ],
)


if __name__ == "__main__":
    os.environ.setdefault("CELERY_WORKER_NAME", "image-processor")
    argv = [
        "worker",
        "--loglevel=INFO",
        "--concurrency=2",
        "--queues=image_processing",
    ]
    celery_app.start(argv=argv)