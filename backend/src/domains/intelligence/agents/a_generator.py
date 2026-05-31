"""
Agent A — Invoice Generator / Extractor.

Parses raw document text (OCR output, email body, pasted text) and returns a
structured ExtractedInvoice. Uses Claude with few-shot prompting.
"""
from __future__ import annotations

import json

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from src.domains.intelligence.prompts.a_generator import GENERATOR_FEW_SHOT, GENERATOR_SYSTEM
from src.domains.intelligence.schemas import ExtractedInvoice, ExtractedLineItem, OrchestratorState


def make_a_generator_node(llm: ChatAnthropic):
    async def a_generator_node(state: OrchestratorState) -> dict:
        # Pull the raw document text from context or the last human message
        raw_text: str = state["context"].get("document_text", "")
        if not raw_text:
            for msg in reversed(state["messages"]):
                if isinstance(msg, HumanMessage):
                    raw_text = msg.content
                    break

        human_content = f"{GENERATOR_FEW_SHOT}\n\n### Your task\nTEXT:\n{raw_text}\n\nRESPONSE:"
        response = await llm.ainvoke(
            [SystemMessage(content=GENERATOR_SYSTEM), HumanMessage(content=human_content)]
        )

        invoice = _parse_invoice(response.content)
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


def _parse_invoice(raw: str) -> ExtractedInvoice:
    try:
        text = raw.strip()
        if "```" in text:
            text = text.split("```")[1].lstrip("json").strip()
        data = json.loads(text)
        items = [ExtractedLineItem(**li) for li in data.pop("line_items", [])]
        return ExtractedInvoice(**data, line_items=items)
    except Exception:
        return ExtractedInvoice(confidence=0.0)
