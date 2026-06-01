from celery import Celery

from src.core.config import settings

celery_app = Celery(
    "finguard",
    broker=settings.CELERY_BROKER_URL or settings.RABBITMQ_URL,
    backend=settings.CELERY_RESULT_BACKEND or settings.REDIS_URL,
    include=[
        "src.workers.tasks.ocr",
        "src.workers.tasks.batch",
        "src.workers.tasks.reporting_tasks",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_routes={
        "ocr.*":       {"queue": "ocr_processing"},
        "batch.*":     {"queue": "batch_processing"},
        "watchdog.*":  {"queue": "watchdog"},
        "reporting.*": {"queue": "batch_processing"},
    },
    beat_schedule={
        "consume-watchdog-events": {
            "task": "watchdog.consume_events",
            "schedule": 30.0,  # every 30 seconds per SYSTEM_OVERVIEW.md
        },
    },
)
