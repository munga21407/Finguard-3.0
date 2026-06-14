"""
Receipt Scanner graph nodes — multimodal OCR + expense categorisation.

This pipeline is deliberately decoupled from Agent A (invoice generation):
a receipt is a *proof of spend* that becomes an Expense, whereas an invoice is a
*request for payment* that becomes an Invoice.  Conflating them would force one
prompt/schema to serve two very different document shapes.

Graph topology (see orchestrator.build_receipt_graph):

    START → receipt_ocr → receipt_classifier → END

Each node is defensive: a Gemini failure degrades to a low-confidence result
plus an entry in ``error_messages`` rather than crashing the graph, so the HTTP
layer can still return a (possibly empty) form for the user to complete by hand
— the human-in-the-loop fallback.
"""
from __future__ import annotations

import base64
from typing import Any

from google.genai import types
from langchain_core.messages import AIMessage

from src.core.config import settings
from src.core.logging import logger
from src.domains.intelligence.llm_client import get_gemini_client
from src.domains.intelligence.schemas import OrchestratorState, ReceiptExtraction
from src.domains.intelligence.tools.vision_ocr import extract_receipt

# Expense categories the scanner may assign.  Kept intentionally small and
# aligned with the frontend ReceiptScanner form's <select> so the suggested
# value is always a valid option the user can accept without re-mapping.
RECEIPT_CATEGORIES: tuple[str, ...] = (
    "supplies",
    "services",
    "utilities",
    "travel",
    "other",
)

_CLASSIFIER_PROMPT = """\
You are categorising a business expense for a Kenyan SME.

Receipt details:
  merchant: {merchant}
  line items: {items}
  total: {total} {currency}

Choose the single best category from this exact list:
  supplies   — physical goods, stock, hardware, stationery
  services   — professional/contracted services, software subscriptions, repairs
  utilities  — electricity, water, internet, airtime, rent
  travel     — fuel, fares, lodging, per-diem
  other      — anything that does not clearly fit the above

Respond with ONLY the category word in lowercase.
"""


# ── Node 1: OCR ───────────────────────────────────────────────────────────────

def make_receipt_ocr_node() -> Any:
    """Decode the uploaded image from context and run Gemini vision OCR."""

    async def receipt_ocr_node(state: OrchestratorState) -> dict[str, Any]:
        context = dict(state["context"])
        image_b64: str = context.get("image_bytes_b64", "")

        if not image_b64:
            context["receipt_extraction"] = ReceiptExtraction().model_dump()
            return {
                "messages": [
                    AIMessage(
                        content="[receipt_ocr] No image provided.",
                        name="receipt_ocr",
                    )
                ],
                "context": context,
                "error_messages": ["receipt_ocr: missing image_bytes_b64"],
            }

        try:
            image_bytes = base64.b64decode(image_b64)
            extraction = await extract_receipt(
                image_bytes, context.get("mime_type")
            )
            context["receipt_extraction"] = extraction.model_dump()
            summary = (
                f"Extracted receipt from {extraction.merchant_name or 'unknown merchant'} "
                f"for {extraction.total_amount or 0} {extraction.currency} "
                f"(confidence {extraction.confidence:.0%})."
            )
            return {
                "messages": [AIMessage(content=summary, name="receipt_ocr")],
                "context": context,
            }
        except Exception as exc:  # noqa: BLE001 — degrade, don't crash the graph
            logger.warning("receipt_ocr: extraction failed", error=str(exc))
            context["receipt_extraction"] = ReceiptExtraction().model_dump()
            return {
                "messages": [
                    AIMessage(
                        content=f"[receipt_ocr] OCR failed: {exc}",
                        name="receipt_ocr",
                    )
                ],
                "context": context,
                "error_messages": [f"receipt_ocr: {exc}"],
            }

    return receipt_ocr_node


# ── Node 2: categorisation ────────────────────────────────────────────────────

def make_receipt_classifier_node() -> Any:
    """Suggest an expense category from the OCR'd receipt fields."""

    async def receipt_classifier_node(state: OrchestratorState) -> dict[str, Any]:
        context = dict(state["context"])
        raw = context.get("receipt_extraction") or {}

        merchant = raw.get("merchant_name") or "unknown"
        items = ", ".join(raw.get("line_items") or []) or "n/a"
        total = raw.get("total_amount") or 0
        currency = raw.get("currency") or "KES"

        suggested = "other"
        try:
            client = get_gemini_client()
            response = await client.aio.models.generate_content(
                model=settings.GEMINI_MODEL,
                contents=_CLASSIFIER_PROMPT.format(
                    merchant=merchant, items=items, total=total, currency=currency
                ),
                config=types.GenerateContentConfig(temperature=0.0),
            )
            candidate = (response.text or "").strip().lower()
            # Guard: only accept a value from the allowed set; default otherwise.
            suggested = candidate if candidate in RECEIPT_CATEGORIES else "other"
        except Exception as exc:  # noqa: BLE001 — categorisation is best-effort
            logger.warning("receipt_classifier: classification failed", error=str(exc))

        context["suggested_category"] = suggested
        return {
            "messages": [
                AIMessage(
                    content=f"Suggested category: {suggested}",
                    name="receipt_classifier",
                )
            ],
            "context": context,
        }

    return receipt_classifier_node
