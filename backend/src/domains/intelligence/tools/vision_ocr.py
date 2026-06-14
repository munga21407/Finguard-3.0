"""
Reusable Gemini-vision OCR for receipt images.

This is the single source of truth for receipt vision extraction.  Both the
interactive Receipt Scanner graph (``agents/receipt_scanner.py``) and the
batch Celery task (``workers/tasks/ocr.py``) call ``extract_receipt`` so the
prompt and Gemini configuration never drift between the sync and async paths.
"""
from __future__ import annotations

from google.genai import types

from src.core.config import settings
from src.domains.intelligence.llm_client import get_gemini_client
from src.domains.intelligence.schemas import ReceiptExtraction

# Canonical receipt-extraction prompt.  Tuned for Kenyan SME receipts where the
# KRA PIN and KES amounts are the highest-value fields for downstream tax
# (Agent F) and budgeting workflows.
RECEIPT_OCR_PROMPT = """\
Extract structured data from this receipt image for Finguard, a Kenyan SME platform.

Focus on:
  - merchant_name: the business name printed on the receipt
  - date: transaction date (ISO-8601 preferred, null if unreadable)
  - total_amount: the final payable amount as a float
  - currency: 3-letter ISO code — default KES if not shown
  - kra_pin: the KRA (Kenya Revenue Authority) PIN if printed (e.g. P051234567X)
  - line_items: list of item/service description strings

Return null for any field not clearly legible. Set confidence = 1.0 only when
all core fields are unambiguous.
"""

# Magic-byte → MIME map for the formats Gemini vision accepts.
_JPEG_MAGIC = b"\xff\xd8"
_PNG_MAGIC = b"\x89PNG"
_PDF_MAGIC = b"%PDF"
_RIFF_MAGIC = b"RIFF"
_WEBP_TAG = b"WEBP"


def detect_image_mime(image_bytes: bytes) -> str:
    """Best-effort MIME sniff from a file's leading bytes.

    Defaults to image/jpeg (the most common phone-camera receipt format) when
    the signature is unrecognised, since Gemini tolerates a slightly wrong hint
    far better than a missing one.
    """
    if image_bytes[:2] == _JPEG_MAGIC:
        return "image/jpeg"
    if image_bytes[:4] == _PNG_MAGIC:
        return "image/png"
    if image_bytes[:4] == _RIFF_MAGIC and image_bytes[8:12] == _WEBP_TAG:
        return "image/webp"
    if image_bytes[:4] == _PDF_MAGIC:
        return "application/pdf"
    return "image/jpeg"


async def extract_receipt(
    image_bytes: bytes,
    mime_type: str | None = None,
) -> ReceiptExtraction:
    """Run Gemini multimodal OCR over a receipt image and return structured data.

    Args:
        image_bytes: raw bytes of the receipt image/PDF.
        mime_type:   optional explicit MIME type; sniffed from the bytes if None.

    Returns:
        A validated ReceiptExtraction.  Unreadable fields come back as null —
        the caller decides whether confidence is high enough to act on.
    """
    mime = mime_type or detect_image_mime(image_bytes)
    client = get_gemini_client()
    response = await client.aio.models.generate_content(
        model=settings.GEMINI_MODEL,
        # google-genai stubs type `contents` with an invariant list union, so a
        # plain list[Part] is rejected even though it is valid at runtime.
        contents=[  # type: ignore[arg-type]
            types.Part.from_bytes(data=image_bytes, mime_type=mime),
            types.Part.from_text(text=RECEIPT_OCR_PROMPT),
        ],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=ReceiptExtraction,
            temperature=0.0,
        ),
    )
    return ReceiptExtraction.model_validate_json(response.text or "{}")
