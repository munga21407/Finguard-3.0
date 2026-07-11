"""
Reusable vision OCR for receipt images.

This is the single source of truth for receipt vision extraction.  Both the
interactive Receipt Scanner graph (``agents/receipt_scanner.py``) and the
batch Celery task (``workers/tasks/ocr.py``) call ``extract_receipt`` so the
prompt and the model configuration never drift between the sync and async paths.

Sprint 6 (S6-6):
  - The expense taxonomy in the prompt is built from the ``receipt`` tuning
    section (``get_receipt_tuning().categories``) so operators can extend it
    without a deploy.
  - A low-confidence scan (below ``receipt.ocr_min_confidence``) is re-run once
    with a higher-fidelity vision model (``VISION_RETRY_MODEL``, disabled by
    default); the higher-confidence of the two reads is returned.
"""
from __future__ import annotations

from src.core.config import settings
from src.core.logging import logger
from src.domains.intelligence.llm_client import generate_vision_content
from src.domains.intelligence.schemas import ReceiptExtraction
from src.domains.intelligence.tuning import get_receipt_tuning

# Human-readable hints for the base taxonomy; extra operator-added categories
# are listed by name (the model still gets the label to classify against).
_CATEGORY_DESCRIPTIONS: dict[str, str] = {
    "supplies": "physical goods, stock, hardware, stationery",
    "services": "professional/contracted services, software subscriptions, repairs",
    "utilities": "electricity, water, internet, airtime, rent",
    "travel": "fuel, fares, lodging, per-diem",
    "other": "anything that does not clearly fit the above",
}

# Canonical receipt-extraction prompt.  Tuned for Kenyan SME receipts where the
# KRA PIN and KES amounts are the highest-value fields for downstream tax
# (Agent F) and budgeting workflows.  ``{categories}`` is filled from config.
_RECEIPT_OCR_PROMPT_TEMPLATE = """\
Extract structured data from this receipt image for Finguard, a Kenyan SME platform.

Focus on:
  - merchant_name: the business name printed on the receipt
  - date: transaction date (ISO-8601 preferred, null if unreadable)
  - total_amount: the final payable amount as a float
  - currency: 3-letter ISO code — default KES if not shown
  - kra_pin: the KRA (Kenya Revenue Authority) PIN if printed (e.g. P051234567X)
  - line_items: list of item/service description strings
  - suggested_category: the single best expense category, chosen from EXACTLY
    this list (lowercase):
{categories}

Return null for any field not clearly legible (except suggested_category, which
must always be one of the words above; use "other" when unsure). Set
confidence = 1.0 only when all core fields are unambiguous.
"""


def _build_category_block(categories: tuple[str, ...]) -> str:
    lines = []
    for cat in categories:
        desc = _CATEGORY_DESCRIPTIONS.get(cat)
        lines.append(f"      {cat}   — {desc}" if desc else f"      {cat}")
    return "\n".join(lines)


def build_receipt_prompt(categories: tuple[str, ...] | None = None) -> str:
    """Render the OCR prompt for the given (or configured) expense taxonomy."""
    cats = categories or get_receipt_tuning().categories
    return _RECEIPT_OCR_PROMPT_TEMPLATE.format(categories=_build_category_block(cats))


# Back-compat: the default-taxonomy rendered prompt (was a module constant).
RECEIPT_OCR_PROMPT = build_receipt_prompt()

# Magic-byte → MIME map for the formats the model vision accepts.
_JPEG_MAGIC = b"\xff\xd8"
_PNG_MAGIC = b"\x89PNG"
_PDF_MAGIC = b"%PDF"
_RIFF_MAGIC = b"RIFF"
_WEBP_TAG = b"WEBP"


def detect_image_mime(image_bytes: bytes) -> str:
    """Best-effort MIME sniff from a file's leading bytes.

    Defaults to image/jpeg (the most common phone-camera receipt format) when
    the signature is unrecognised, since the model tolerates a slightly wrong hint
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
    """Run the model multimodal OCR over a receipt image and return structured data.

    A first pass runs on the default vision model.  If the read is low-confidence
    (below ``receipt.ocr_min_confidence``) and a distinct higher-fidelity model
    is configured, a single second pass runs on that model and the more
    confident of the two results is returned (S6-6).

    Args:
        image_bytes: raw bytes of the receipt image/PDF.
        mime_type:   optional explicit MIME type; sniffed from the bytes if None.

    Returns:
        A validated ReceiptExtraction.  Unreadable fields come back as null —
        the caller decides whether confidence is high enough to act on.
    """
    mime = mime_type or detect_image_mime(image_bytes)
    tuning = get_receipt_tuning()
    prompt = build_receipt_prompt(tuning.categories)

    result = await generate_vision_content(
        prompt,
        image_bytes=image_bytes,
        mime_type=mime,
        response_schema=ReceiptExtraction,
        temperature=0.0,
    )

    retry_model = settings.VISION_RETRY_MODEL
    needs_retry = (
        tuning.hifi_retry_enabled
        and result.confidence < tuning.ocr_min_confidence
        and bool(retry_model)
        and retry_model != settings.LLM_MODEL
    )
    if not needs_retry:
        return result

    logger.info(
        "vision_ocr: low-confidence read — re-scanning with higher-fidelity model",
        first_confidence=result.confidence,
        floor=tuning.ocr_min_confidence,
        retry_model=retry_model,
    )
    try:
        second = await generate_vision_content(
            prompt,
            image_bytes=image_bytes,
            mime_type=mime,
            response_schema=ReceiptExtraction,
            temperature=0.0,
            model=retry_model,
        )
    except Exception as exc:  # noqa: BLE001 — keep the first read on retry failure
        logger.warning("vision_ocr: higher-fidelity re-scan failed", error=str(exc))
        return result

    # Keep whichever pass is more confident (ties favour the cheaper first read).
    return second if second.confidence > result.confidence else result
