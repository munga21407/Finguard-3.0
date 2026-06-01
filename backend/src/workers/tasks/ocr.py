"""
OCR processing Celery tasks.

All tasks route to the `ocr_processing` queue.  Each task is bound (self)
so it can retry itself with exponential back-off on transient failures.
"""
from __future__ import annotations

from src.workers.tasks.celery_app import celery_app


@celery_app.task(
    bind=True,
    name="ocr.process_document",
    queue="ocr_processing",
    max_retries=3,
    default_retry_delay=60,
)
def process_document_ocr(self, document_id: str, storage_path: str) -> dict:
    """
    Extract text from an uploaded document via OCR.

    Args:
        document_id:   UUID of the document record.
        storage_path:  File path or object-storage key of the image/PDF.

    Returns:
        dict with keys: document_id, status, text, confidence.
    """
    try:
        # TODO: integrate Tesseract / EasyOCR / Google Vision
        # Example integration point:
        #   from pytesseract import image_to_string
        #   from PIL import Image
        #   img = Image.open(storage_path)
        #   text = image_to_string(img)
        return {
            "document_id": document_id,
            "status": "processed",
            "text": "",
            "confidence": 0.0,
        }
    except Exception as exc:
        raise self.retry(exc=exc)


@celery_app.task(
    bind=True,
    name="ocr.process_receipt",
    queue="ocr_processing",
    max_retries=3,
    default_retry_delay=60,
)
def process_receipt_ocr(self, receipt_id: str, image_bytes_b64: str) -> dict:
    """
    Extract structured transaction data from a receipt image.

    Args:
        receipt_id:       UUID of the receipt record.
        image_bytes_b64:  Base64-encoded image bytes.

    Returns:
        dict with keys: receipt_id, status, merchant, amount, date, currency.
    """
    try:
        # TODO: integrate EasyOCR + Gemini vision extraction
        return {
            "receipt_id": receipt_id,
            "status": "processed",
            "merchant": None,
            "amount": None,
            "date": None,
            "currency": "KES",
        }
    except Exception as exc:
        raise self.retry(exc=exc)


@celery_app.task(
    bind=True,
    name="ocr.process_invoice_image",
    queue="ocr_processing",
    max_retries=3,
    default_retry_delay=60,
)
def process_invoice_image(self, invoice_id: str, storage_path: str) -> dict:
    """
    OCR-extract structured invoice data from a scanned invoice image.

    Args:
        invoice_id:    UUID of the pending invoice record.
        storage_path:  File path or object-storage key of the invoice scan.

    Returns:
        dict with keys: invoice_id, status, extracted_fields.
    """
    try:
        # TODO: integrate OCR → Agent A pipeline
        return {
            "invoice_id": invoice_id,
            "status": "processed",
            "extracted_fields": {},
        }
    except Exception as exc:
        raise self.retry(exc=exc)
