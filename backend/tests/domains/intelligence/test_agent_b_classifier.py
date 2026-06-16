"""Unit tests for Agent B (Transaction Classifier) Gemini scoring + guards.

``_classify_via_gemini`` has two correctness guards worth pinning: every input
entry_id must appear in the output (missing ones backfilled as ``other``), and
any category outside the taxonomy is coerced to ``other``. The Gemini client is
mocked, so the test is deterministic.
"""
from __future__ import annotations

from typing import Any

import pytest

from src.domains.intelligence.agents import b_classifier
from src.domains.intelligence.agents.b_classifier import _classify_via_gemini
from src.domains.intelligence.prompts.b_classifier import TRANSACTION_TAXONOMY
from src.domains.intelligence.schemas import (
    BatchClassificationResult,
    TransactionClassification,
)

_VALID_CATEGORY = next(iter(TRANSACTION_TAXONOMY))


def _entry(eid: str) -> dict[str, Any]:
    return {"entry_id": eid, "narrative": "x", "amount": 1.0, "transaction_type": "debit"}


def _patch_llm(monkeypatch: pytest.MonkeyPatch, result: BatchClassificationResult) -> None:
    """Patch the provider-agnostic facade the agent now depends on."""
    async def _gen(_prompt: str, _schema: Any, **_kw: Any) -> BatchClassificationResult:
        return result

    monkeypatch.setattr(b_classifier, "generate_structured_content", _gen)


@pytest.mark.asyncio
async def test_empty_entries_short_circuits() -> None:
    # No entries → no LLM call, empty result.
    assert await _classify_via_gemini([]) == []


@pytest.mark.asyncio
async def test_missing_entry_id_backfilled_as_other(monkeypatch: pytest.MonkeyPatch) -> None:
    # LLM returns only e1; e2 must be backfilled as "other"/0.0.
    _patch_llm(
        monkeypatch,
        BatchClassificationResult(
            classifications=[
                TransactionClassification(entry_id="e1", category=_VALID_CATEGORY, confidence=0.9)
            ]
        ),
    )
    out = await _classify_via_gemini([_entry("e1"), _entry("e2")])
    by_id = {c.entry_id: c for c in out}
    assert set(by_id) == {"e1", "e2"}
    assert by_id["e2"].category == "other" and by_id["e2"].confidence == 0.0


@pytest.mark.asyncio
async def test_out_of_taxonomy_category_coerced(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_llm(
        monkeypatch,
        BatchClassificationResult(
            classifications=[
                TransactionClassification(entry_id="e1", category="not_a_real_category", confidence=0.8)
            ]
        ),
    )
    out = await _classify_via_gemini([_entry("e1")])
    assert out[0].category == "other" and out[0].confidence == 0.0
