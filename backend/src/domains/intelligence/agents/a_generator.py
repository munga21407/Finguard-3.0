"""
Agent A — Invoice Generator / Extractor.

Parses raw document text (OCR output, email body, pasted text) and returns a
structured ExtractedInvoice using Gemini's native response_schema mode —
no JSON prompt hacking, no fallback parsing.

Fast-path: if context["ocr_extracted_fields"] is already populated (set by the
process_invoice_image Celery task), the node validates the dict against
ExtractedInvoice and returns immediately — skipping the second Gemini call.
"""
from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage, HumanMessage
from pydantic import ValidationError

from src.core.logging import logger
from src.domains.intelligence.llm_client import generate_structured_content
from src.domains.intelligence.prompts.a_generator import GENERATOR_HUMAN, GENERATOR_SYSTEM
from src.domains.intelligence.schemas import ExtractedInvoice, OrchestratorState

# OCR fast-path acceptance floor (Sprint 4): a pre-parsed OCR dict is only trusted
# without a second Gemini pass when its self-reported confidence clears this bar;
# below it we fall through to full text extraction rather than accept a shaky read.
_OCR_FASTPATH_MIN_CONFIDENCE = 0.6


def make_a_generator_node(llm: Any = None) -> Any:  # llm kept for signature compatibility
    async def a_generator_node(state: OrchestratorState) -> dict[str, Any]:

        # ── Fast-path: pre-parsed OCR output from process_invoice_image ──────
        ocr_fields = state["context"].get("ocr_extracted_fields")
        if ocr_fields and isinstance(ocr_fields, dict):
            try:
                invoice = ExtractedInvoice.model_validate(ocr_fields)
            except ValidationError:
                # OCR dict doesn't satisfy the schema — fall through to text extraction
                invoice = None
            # Confidence gate: only short-circuit the LLM when the OCR read is
            # trustworthy; a low-confidence dict falls through to full extraction.
            if invoice is not None and invoice.confidence >= _OCR_FASTPATH_MIN_CONFIDENCE:
                summary = (
                    f"Extracted invoice {invoice.invoice_number or '(unknown)'} "
                    f"from {invoice.vendor or '(unknown vendor)'} — "
                    f"total {invoice.currency} {invoice.total} "
                    f"(confidence {invoice.confidence:.0%}, source: ocr)"
                )
                return {
                    "messages": [AIMessage(content=summary, name="a_generator")],
                    "context": {"extracted_invoice": invoice.model_dump()},
                }
            if invoice is not None:
                logger.info(
                    "a_generator: OCR confidence below fast-path floor — "
                    "re-extracting via Gemini",
                    ocr_confidence=invoice.confidence,
                    floor=_OCR_FASTPATH_MIN_CONFIDENCE,
                )

        # ── Standard path: Gemini extraction from raw document text ──────────
        raw_text: str = state["context"].get("document_text", "")
        if not raw_text:
            for msg in reversed(state["messages"]):
                if isinstance(msg, HumanMessage):
                    raw_text = str(msg.content)
                    break

        prompt = (
            f"{GENERATOR_SYSTEM}\n\n"
            + GENERATOR_HUMAN.format(raw_text=raw_text)
        )

        try:
            invoice = await generate_structured_content(prompt, ExtractedInvoice)
        except Exception as exc:
            error_msg = f"[a_generator] Gemini extraction failed: {exc}"
            return {
                "messages": [AIMessage(content=error_msg, name="a_generator")],
            }

        summary = (
            f"Extracted invoice {invoice.invoice_number or '(unknown)'} "
            f"from {invoice.vendor or '(unknown vendor)'} — "
            f"total {invoice.currency} {invoice.total} "
            f"(confidence {invoice.confidence:.0%})"
        )

        return {
            "messages": [AIMessage(content=summary, name="a_generator")],
            "context": {"extracted_invoice": invoice.model_dump()},
        }

    return a_generator_node
