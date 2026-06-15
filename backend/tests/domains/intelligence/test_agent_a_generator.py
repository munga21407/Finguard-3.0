"""Node-level tests for Agent A (Invoice Generator): OCR fast-path, Gemini
extraction, and graceful degradation on LLM failure.

The Gemini call is mocked at the module lookup name so the test is fast/free.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.messages import HumanMessage

from src.domains.intelligence.agents.a_generator import make_a_generator_node
from src.domains.intelligence.schemas import ExtractedInvoice

_LLM = "src.domains.intelligence.agents.a_generator.generate_structured_content"


def _invoice(**kw: Any) -> ExtractedInvoice:
    base: dict[str, Any] = {
        "vendor": "Acme Ltd",
        "customer": "TechFlow",
        "invoice_number": "INV-001",
        "issue_date": None,
        "due_date": None,
        "currency": "KES",
        "total": 45_000.0,
        "confidence": 0.92,
    }
    base.update(kw)
    return ExtractedInvoice(**base)


def _state(**ctx: Any) -> dict[str, Any]:
    return {
        "messages": [HumanMessage(content="Bill Acme KES 45000")],
        "gen_ui_payloads": [],
        "error_messages": [],
        "next": "a_generator",
        "context": ctx,
        "session_id": "s1",
        "user_id": "u1",
        "mode": "actions",
    }


@pytest.mark.asyncio
async def test_ocr_fast_path_skips_llm() -> None:
    node = make_a_generator_node()
    ocr = _invoice().model_dump()
    with patch(_LLM, new_callable=AsyncMock) as mock_llm:
        result = await node(_state(ocr_extracted_fields=ocr))
    mock_llm.assert_not_called()  # valid OCR dict → no Gemini call
    assert result["context"]["extracted_invoice"]["invoice_number"] == "INV-001"
    assert result["messages"][0].name == "a_generator"


@pytest.mark.asyncio
async def test_standard_path_extracts_via_gemini() -> None:
    node = make_a_generator_node()
    with patch(_LLM, new_callable=AsyncMock, return_value=_invoice()):
        result = await node(_state(document_text="Bill Acme KES 45000"))
    inv = result["context"]["extracted_invoice"]
    assert inv["vendor"] == "Acme Ltd" and inv["total"] == 45_000.0


@pytest.mark.asyncio
async def test_llm_failure_degrades_without_crashing() -> None:
    node = make_a_generator_node()
    with patch(_LLM, new_callable=AsyncMock, side_effect=RuntimeError("gemini down")):
        result = await node(_state(document_text="Bill Acme KES 45000"))
    # No crash: an error message is returned and no invoice is written.
    assert "failed" in result["messages"][0].content.lower()
    assert "extracted_invoice" not in result["context"]
