from celery import Celery  # type: ignore[import-untyped]
from celery.schedules import crontab  # type: ignore[import-untyped]

from src.core.config import settings

celery_app = Celery(
    "finguard",
    broker=settings.CELERY_BROKER_URL or settings.RABBITMQ_URL,
    backend=settings.CELERY_RESULT_BACKEND or settings.REDIS_URL,
    include=[
        "src.workers.tasks.ocr",
        "src.workers.tasks.batch",
        "src.workers.tasks.reporting_tasks",
        "src.workers.tasks.dlq_tasks",
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
        "classify-unclassified-ledger-entries": {
            "task": "batch.classify_unclassified_ledger_entries",
            "schedule": 300.0,  # every 5 minutes
        },
        "run-batch-reconciliation": {
            "task": "batch.run_batch_reconciliation",
            "schedule": 900.0,  # every 15 minutes
        },
        "dispatch-monthly-reports": {
            "task": "reporting.dispatch_monthly_reports",
            "schedule": crontab(hour=0, minute=0, day_of_month="1"),
        },
        "drain-watchdog-dlq": {
            "task": "dlq.drain_watchdog_dlq",
            "schedule": 900.0,   # every 15 minutes — matches the batch reconciliation cadence
            "kwargs": {"batch_size": 100},
        },
        "enforce-data-retention": {
            "task": "batch.enforce_data_retention",
            # Weekly on Sunday at 02:00 UTC — low-traffic window.
            # 7-year retention window means only historical rows are touched;
            # no impact on current operational data.
            "schedule": crontab(hour=2, minute=0, day_of_week="sunday"),
        },
    },
)
