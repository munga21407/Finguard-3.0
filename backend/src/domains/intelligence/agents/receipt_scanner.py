"""
Receipt Scanner graph nodes — multimodal OCR + expense categorisation.

This pipeline is deliberately decoupled from Agent A (invoice generation):
a receipt is a *proof of spend* that becomes an Expense, whereas an invoice is a
*request for payment* that becomes an Invoice.  Conflating them would force one
prompt/schema to serve two very different document shapes.

Graph topology (see orchestrator.build_receipt_graph):

    START → receipt_ocr → receipt_classifier → END

Each node is defensive: a model failure degrades to a low-confidence result
plus an entry in ``error_messages`` rather than crashing the graph, so the HTTP
layer can still return a (possibly empty) form for the user to complete by hand
— the human-in-the-loop fallback.
"""
from __future__ import annotations

import base64
from typing import Any

from langchain_core.messages import AIMessage

from src.core.logging import logger
from src.domains.intelligence.schemas import (
    RECEIPT_CATEGORIES,
    OrchestratorState,
    ReceiptExtraction,
    effective_receipt_categories,
)
from src.domains.intelligence.tools.vision_ocr import extract_receipt

# ``RECEIPT_CATEGORIES`` is re-exported from schemas (single source of truth,
# also used by the vision prompt) — kept importable here for back-compat.
__all__ = ["RECEIPT_CATEGORIES", "make_receipt_classifier_node", "make_receipt_ocr_node"]


# ── Node 1: OCR ───────────────────────────────────────────────────────────────

def make_receipt_ocr_node() -> Any:
    """Decode the uploaded image from context and run the model vision OCR."""

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
    """Surface the expense category already produced by the OCR vision call.

    Sprint 3: categorisation is now a field of the single ``extract_receipt``
    vision call, so this node makes **no** LLM call — it just reads
    ``suggested_category`` off the extraction, clamps it to the allowed set
    (defence in depth; the schema validator already does this), and publishes it
    to ``context["suggested_category"]`` for the HTTP layer / form.
    """

    async def receipt_classifier_node(state: OrchestratorState) -> dict[str, Any]:
        context = dict(state["context"])
        raw = context.get("receipt_extraction") or {}

        candidate = str(raw.get("suggested_category") or "other").strip().lower()
        suggested = candidate if candidate in effective_receipt_categories() else "other"

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
