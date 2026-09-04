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
        "src.workers.tasks.email_tasks",
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
        "email.*":     {"queue": "notifications"},
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
        "run-batch-bank-reconciliation": {
            "task": "batch.run_batch_bank_reconciliation",
            "schedule": 900.0,  # every 15 minutes — matches the M-Pesa cadence
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
        "retrain-agent-e-models": {
            "task": "batch.retrain_agent_e_models",
            # Weekly on Sunday at 03:00 UTC — after retention enforcement, in the
            # same low-traffic window.  Re-fits each customer's Agent E
            # IsolationForest from the trailing 90 days of categorized debits.
            "schedule": crontab(hour=3, minute=0, day_of_week="sunday"),
        },
        "enforce-checkpoint-retention": {
            "task": "batch.enforce_checkpoint_retention",
            # Weekly on Sunday at 04:00 UTC — after the other two Sunday jobs,
            # same low-traffic window. No-op (tables stay empty) wherever
            # LANGGRAPH_CHECKPOINTING_ENABLED is off.
            "schedule": crontab(hour=4, minute=0, day_of_week="sunday"),
        },
        "flush-email-outbox": {
            "task": "email.flush_outbox",
            # Drain the transactional email outbox; cadence is operator-tunable via
            # EMAIL_POLL_INTERVAL (default 60s).
            "schedule": settings.EMAIL_POLL_INTERVAL,
        },
        "dispatch-payment-reminders": {
            "task": "email.dispatch_payment_reminders",
            # Daily at 08:00 UTC — enqueue due-soon/overdue reminders (idempotent
            # per invoice+tier, so a daily sweep escalates without re-nagging).
            "schedule": crontab(hour=8, minute=0),
        },
    },
)
