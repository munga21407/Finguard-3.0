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

from src.domains.intelligence.llm_client import generate_structured_content
from src.domains.intelligence.prompts.a_generator import GENERATOR_HUMAN, GENERATOR_SYSTEM
from src.domains.intelligence.schemas import ExtractedInvoice, OrchestratorState


def make_a_generator_node(llm: Any = None) -> Any:  # llm kept for signature compatibility
    async def a_generator_node(state: OrchestratorState) -> dict[str, Any]:

        # ── Fast-path: pre-parsed OCR output from process_invoice_image ──────
        ocr_fields = state["context"].get("ocr_extracted_fields")
        if ocr_fields and isinstance(ocr_fields, dict):
            try:
                invoice = ExtractedInvoice.model_validate(ocr_fields)
                state["context"]["extracted_invoice"] = invoice.model_dump()
                summary = (
                    f"Extracted invoice {invoice.invoice_number or '(unknown)'} "
                    f"from {invoice.vendor or '(unknown vendor)'} — "
                    f"total {invoice.currency} {invoice.total} "
                    f"(confidence {invoice.confidence:.0%}, source: ocr)"
                )
                return {
                    "messages": [AIMessage(content=summary, name="a_generator")],
                    "context": state["context"],
                }
            except ValidationError:
                # OCR dict doesn't satisfy the schema — fall through to text extraction
                pass

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
                "context": state["context"],
            }

        state["context"]["extracted_invoice"] = invoice.model_dump()

        summary = (
            f"Extracted invoice {invoice.invoice_number or '(unknown)'} "
            f"from {invoice.vendor or '(unknown vendor)'} — "
            f"total {invoice.currency} {invoice.total} "
            f"(confidence {invoice.confidence:.0%})"
        )

        return {
            "messages": [AIMessage(content=summary, name="a_generator")],
            "context": state["context"],
        }

    return a_generator_node
