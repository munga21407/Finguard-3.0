"""
Agent A — Invoice Generator / Extractor.

Parses raw document text (OCR output, email body, pasted text) and returns a
structured ExtractedInvoice using Gemini's native response_schema mode —
no JSON prompt hacking, no fallback parsing.
"""
from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage, HumanMessage

from src.domains.intelligence.llm_client import generate_structured_content
from src.domains.intelligence.prompts.a_generator import GENERATOR_SYSTEM
from src.domains.intelligence.schemas import ExtractedInvoice, OrchestratorState


def make_a_generator_node(llm: Any = None) -> Any:  # llm kept for signature compatibility
    async def a_generator_node(state: OrchestratorState) -> dict[str, Any]:
        # Pull raw document text from context or the last human message
        raw_text: str = state["context"].get("document_text", "")
        if not raw_text:
            for msg in reversed(state["messages"]):
                if isinstance(msg, HumanMessage):
                    raw_text = str(msg.content)
                    break

        prompt = (
            f"{GENERATOR_SYSTEM}\n\n"
            "Extract the invoice data from the following document text. "
            "Return null for any field that is not explicitly present.\n\n"
            f"DOCUMENT TEXT:\n{raw_text}"
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
