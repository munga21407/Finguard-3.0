from src.workers.tasks.celery_app import celery_app


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def process_document_ocr(self, document_id: str, storage_path: str) -> dict[str, str]:
    """Extract text from an uploaded document via OCR."""
    try:
        # TODO: integrate with OCR provider (e.g. Tesseract, AWS Textract)
        return {"document_id": document_id, "status": "processed", "text": ""}
    except Exception as exc:
        raise self.retry(exc=exc)
