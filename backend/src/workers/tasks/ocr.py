"""
OCR processing Celery tasks.

All tasks route to the `ocr_processing` queue.  Each task is bound (self)
so it can retry itself with exponential back-off on transient failures.

Vision extraction is powered by Gemini 2.5 Flash multimodal capabilities.
Celery workers are synchronous; the async Gemini API is bridged with
asyncio.run() — the same pattern used by reporting_tasks.py.
"""
from __future__ import annotations

import asyncio
import base64
from pathlib import Path
from typing import Any

from src.core.logging import logger
from src.domains.intelligence.llm_client import (
    generate_vision_content,
    generate_vision_text_content,
)
from src.domains.intelligence.schemas import ExtractedInvoice, ReceiptExtraction
from src.domains.intelligence.tools.vision_ocr import extract_receipt
from src.workers.tasks.celery_app import celery_app

# ── Extraction prompts ────────────────────────────────────────────────────────
# NOTE: the receipt prompt now lives in intelligence/tools/vision_ocr.py as the
# single source of truth — this task delegates receipt OCR to extract_receipt().

_DOCUMENT_TEXT_PROMPT = """\
Extract all readable text from this document image for Finguard, a Kenyan SME platform.

Return the text exactly as it appears, preserving layout structure where possible.
Include all numbers, dates, names, and monetary amounts.
If the document is not readable, return an empty string.
"""

_INVOICE_IMAGE_PROMPT = """\
Extract structured invoice data from this document image for Finguard, a Kenyan SME platform.

Pull all of the following fields that are visible:
  vendor, customer, invoice_number, issue_date (ISO-8601), due_date (ISO-8601),
  currency (default KES), subtotal, tax, total, and all line items.

Each line item should capture: description, quantity, unit_price, total.
Return null for any field not clearly visible in the image.
Infer line item totals where quantity × unit_price is calculable.
Set confidence = 1.0 only when all core fields are unambiguously present.
"""

# ── MIME type helper ──────────────────────────────────────────────────────────

_MIME_MAP: dict[str, str] = {
    ".jpg":  "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png":  "image/png",
    ".webp": "image/webp",
    ".gif":  "image/gif",
    ".heic": "image/heic",
    ".heif": "image/heif",
    ".pdf":  "application/pdf",
}


def _mime_type(path: str) -> str:
    return _MIME_MAP.get(Path(path).suffix.lower(), "image/jpeg")


# ── Async Gemini vision helpers ───────────────────────────────────────────────

async def _run_document_text_extraction(image_bytes: bytes, mime_type: str) -> str:
    text = await generate_vision_text_content(
        _DOCUMENT_TEXT_PROMPT,
        image_bytes=image_bytes,
        mime_type=mime_type,
        temperature=0.0,
    )
    return text.strip()


async def _run_invoice_image_extraction(
    image_bytes: bytes,
    mime_type: str,
) -> ExtractedInvoice:
    return await generate_vision_content(
        _INVOICE_IMAGE_PROMPT,
        image_bytes=image_bytes,
        mime_type=mime_type,
        response_schema=ExtractedInvoice,
        temperature=0.0,
    )


# ── Celery tasks ──────────────────────────────────────────────────────────────

@celery_app.task(  # type: ignore[untyped-decorator]
    bind=True,
    name="ocr.process_document",
    queue="ocr_processing",
    max_retries=3,
    default_retry_delay=60,
)
def process_document_ocr(self: Any, document_id: str, storage_path: str) -> dict[str, Any]:
    """
    Extract text from an uploaded document via Gemini multimodal.

    Args:
        document_id:   UUID of the document record.
        storage_path:  Local file path or object-storage key of the image/PDF.

    Returns:
        dict with keys: document_id, status, text, confidence.
        On missing or unreadable file: status = "unreadable", text = "".
    """
    try:
        path = Path(storage_path)
        if not path.exists():
            logger.warning(
                "Document OCR: file not found",
                document_id=document_id,
                path=storage_path,
            )
            return {
                "document_id": document_id,
                "status": "file_not_found",
                "text": "",
                "confidence": 0.0,
            }

        image_bytes = path.read_bytes()
        mime = _mime_type(storage_path)

        extracted_text: str = asyncio.run(
            _run_document_text_extraction(image_bytes, mime)
        )
        confidence = 1.0 if extracted_text else 0.0
        return {
            "document_id": document_id,
            "status": "processed",
            "text": extracted_text,
            "confidence": confidence,
        }

    except OSError as exc:
        logger.warning("Document OCR: cannot read file", document_id=document_id, error=str(exc))
        return {"document_id": document_id, "status": "unreadable", "text": "", "confidence": 0.0}
    except Exception as exc:
        raise self.retry(exc=exc) from exc


@celery_app.task(  # type: ignore[untyped-decorator]
    bind=True,
    name="ocr.process_receipt",
    queue="ocr_processing",
    max_retries=3,
    default_retry_delay=60,
)
def process_receipt_ocr(self: Any, receipt_id: str, image_bytes_b64: str) -> dict[str, Any]:
    """
    Extract structured transaction data from a receipt image via Gemini vision.

    Args:
        receipt_id:       UUID of the receipt record.
        image_bytes_b64:  Base64-encoded image bytes (any Gemini-supported format).

    Returns:
        dict with keys: receipt_id, status, extracted_fields (ReceiptExtraction dict).
        On unreadable image: status = "unreadable", extracted_fields = {}.
        On transient failure: task retries up to 3 times before marking failed.
    """
    try:
        image_bytes = base64.b64decode(image_bytes_b64)

        # MIME is sniffed from the magic bytes inside extract_receipt().
        extraction: ReceiptExtraction = asyncio.run(extract_receipt(image_bytes))
        return {
            "receipt_id": receipt_id,
            "status": "processed",
            "extracted_fields": extraction.model_dump(),
        }

    except (ValueError, UnicodeDecodeError) as exc:
        # Corrupt / non-image payload — do not retry
        logger.warning(
            "Receipt OCR: unreadable image payload", receipt_id=receipt_id, error=str(exc)
        )
        return {
            "receipt_id": receipt_id,
            "status": "unreadable",
            "extracted_fields": {},
        }
    except Exception as exc:
        raise self.retry(exc=exc) from exc


@celery_app.task(  # type: ignore[untyped-decorator]
    bind=True,
    name="ocr.process_invoice_image",
    queue="ocr_processing",
    max_retries=3,
    default_retry_delay=60,
)
def process_invoice_image(self: Any, invoice_id: str, storage_path: str) -> dict[str, Any]:
    """
    OCR-extract structured invoice data from a scanned invoice image via Gemini vision.

    Args:
        invoice_id:    UUID of the pending invoice record.
        storage_path:  Local file path or object-storage key of the invoice scan.

    Returns:
        dict with keys: invoice_id, status, extracted_fields (ExtractedInvoice dict).
        The extracted_fields dict is compatible with Agent A's OCR fast-path:
        set context["ocr_extracted_fields"] = result["extracted_fields"] before
        invoking the a_generator_node to skip the second Gemini call.
    """
    try:
        path = Path(storage_path)
        if not path.exists():
            logger.warning(
                "Invoice OCR: file not found",
                invoice_id=invoice_id,
                path=storage_path,
            )
            return {
                "invoice_id": invoice_id,
                "status": "file_not_found",
                "extracted_fields": {},
            }

        image_bytes = path.read_bytes()
        mime = _mime_type(storage_path)

        extraction: ExtractedInvoice = asyncio.run(
            _run_invoice_image_extraction(image_bytes, mime)
        )
        return {
            "invoice_id": invoice_id,
            "status": "processed",
            "extracted_fields": extraction.model_dump(),
        }

    except OSError as exc:
        logger.warning("Invoice OCR: cannot read file", invoice_id=invoice_id, error=str(exc))
        return {
            "invoice_id": invoice_id,
            "status": "unreadable",
            "extracted_fields": {},
        }
    except Exception as exc:
        raise self.retry(exc=exc) from exc
