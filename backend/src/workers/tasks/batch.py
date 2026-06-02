from src.workers.tasks.celery_app import celery_app


@celery_app.task(bind=True, max_retries=3, default_retry_delay=120)
def run_batch_reconciliation(self, batch_id: str) -> dict[str, str]:
    """Run a batch reconciliation job."""
    try:
        # TODO: implement reconciliation logic
        return {"batch_id": batch_id, "status": "completed"}
    except Exception as exc:
        raise self.retry(exc=exc) from exc
