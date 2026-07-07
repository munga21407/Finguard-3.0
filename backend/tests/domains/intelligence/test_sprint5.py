"""Sprint 5 — feedback loop + output robustness (hermetic: LLM mocked, no DB)."""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from src.domains.intelligence.agents import b_classifier as b
from src.domains.intelligence.agents import h_advisor as h
from src.domains.intelligence.agents import j_summarizer as j
from src.domains.intelligence.schemas import (
    AgentHOutput,
    ExecutiveSummary,
    SummaryBullet,
)
from src.domains.intelligence.services import classification_feedback_service as fb


def _state(ctx: dict[str, Any], **kw: Any) -> dict[str, Any]:
    return {"messages": [], "gen_ui_payloads": [], "error_messages": [],
            "context": ctx, "session_id": "s", "user_id": "u", "mode": "insights", **kw}


# ── S5-5 Agent J: structured bullets, count from structure ────────────────────

@pytest.mark.asyncio
async def test_j_structured_summary_rendered_and_counted() -> None:
    node = j.make_j_summarizer_node()
    out_bullets = ExecutiveSummary(bullets=[
        SummaryBullet(label="Budget Health", text="HEALTHY, anomaly 0.10"),
        SummaryBullet(label="Cash Flow", text="Runway 45 Days"),
    ])
    with patch.object(j, "generate_structured_content", new=AsyncMock(return_value=out_bullets)):
        result = await node(_state({"watchdog_analysis": {"current_state": "HEALTHY"}}))
    ctx = result["context"]
    assert ctx["executive_summary"].startswith("• **Budget Health:**")
    assert len(ctx["executive_summary_bullets"]) == 2       # counted from structure
    assert ctx["executive_summary_bullets"][1]["label"] == "Cash Flow"


@pytest.mark.asyncio
async def test_j_fallback_on_llm_failure() -> None:
    node = j.make_j_summarizer_node()
    with patch.object(j, "generate_structured_content", new=AsyncMock(side_effect=RuntimeError("down"))):
        result = await node(_state({"credit_strategy_result": {"bankability_score": 70, "risk_tier": "MEDIUM"}}))
    assert "Credit Risk" in result["context"]["executive_summary"]


# ── S5-6 Agent J: translation numeric-fidelity guard ──────────────────────────

def test_translation_number_guard() -> None:
    src = [SummaryBullet(label="X", text="Liability KES 64,000 at 16%")]
    good = [SummaryBullet(label="X", text="Deni KES 64,000 kwa 16%")]
    bad = [SummaryBullet(label="X", text="Deni fulani")]   # numbers dropped
    assert j._translation_preserves_numbers(src, good) is True
    assert j._translation_preserves_numbers(src, bad) is False


@pytest.mark.asyncio
async def test_j_keeps_source_when_translation_drops_numbers() -> None:
    node = j.make_j_summarizer_node()
    english = ExecutiveSummary(bullets=[SummaryBullet(label="Tax", text="Liability KES 64,000")])
    broken_translation = ExecutiveSummary(bullets=[SummaryBullet(label="Tax", text="Deni fulani")])
    with patch.object(
        j, "generate_structured_content",
        new=AsyncMock(side_effect=[english, broken_translation]),
    ):
        result = await node(_state(
            {"audit_result": {"tax_type": "VAT"}, "preferred_locale": "sw"}
        ))
    # Fidelity guard rejected the lossy translation → English numerals retained.
    assert "64,000" in result["context"]["executive_summary"]


# ── S5-4 Agent H: thin-context honesty ────────────────────────────────────────

@pytest.mark.asyncio
async def test_h_flags_limited_data_when_no_upstream() -> None:
    node = h.make_h_advisor_node()
    advisor = AgentHOutput(narrative_response="General guidance.", ui_widgets=[])
    with patch.object(h, "generate_structured_content", new=AsyncMock(return_value=advisor)):
        # user_role in ctx avoids the DB role lookup; empty upstream → completeness "none"
        result = await node(_state({"user_role": "owner", "crm_profile": {}}))
    advice = result["context"]["advice"]
    assert advice["data_completeness"] == "none"
    assert advice["narrative_response"].startswith("⚠️ Limited data")


@pytest.mark.asyncio
async def test_h_full_data_no_disclaimer() -> None:
    node = h.make_h_advisor_node()
    advisor = AgentHOutput(narrative_response="Specific guidance.", ui_widgets=[])
    ctx = {
        "user_role": "owner", "crm_profile": {},
        "watchdog_analysis": {"current_state": "HEALTHY"},
        "forecast": {"regime": {"regime": "Normal"}},
        "credit_strategy_result": {"bankability_score": 70},
        "audit_result": {"tax_type": "VAT"},
    }
    with patch.object(h, "generate_structured_content", new=AsyncMock(return_value=advisor)):
        result = await node(_state(ctx))
    advice = result["context"]["advice"]
    assert advice["data_completeness"] == "full"
    assert not advice["narrative_response"].startswith("⚠️")


# ── S5-3 Agent B: configurable batch ──────────────────────────────────────────

def test_classifier_batch_size_from_tuning() -> None:
    from src.domains.intelligence.tuning import (
        ClassifierTuning,
        clear_db_overlay,
        get_agent_tuning,
        get_classifier_tuning,
    )
    assert get_classifier_tuning().batch_size == 50
    try:
        get_agent_tuning.cache_clear()
        from src.domains.intelligence.tuning import set_db_overlay
        set_db_overlay({"classifier": ClassifierTuning(batch_size=7)})
        assert get_classifier_tuning().batch_size == 7
    finally:
        clear_db_overlay()
        get_agent_tuning.cache_clear()


# ── S5-2 few-shot retrieval helpers + injection ───────────────────────────────

def test_fewshot_block_and_query_text() -> None:
    assert fb.format_fewshot_block([]) == ""
    block = fb.format_fewshot_block([fb.FewShotExample("Rent to landlord", "rent_and_premises")])
    assert "rent_and_premises" in block and "Learned corrections" in block
    assert fb.build_query_text([{"narrative": "a"}, {"narrative": "b"}, {"narrative": ""}]) == "a | b"


@pytest.mark.asyncio
async def test_fewshot_retrieval_degrades_gracefully(monkeypatch: pytest.MonkeyPatch) -> None:
    # empty query → no embed, no DB
    assert await fb.get_fewshot_examples(None, "") == []
    # embedding failure → [] (session never touched)
    monkeypatch.setattr(fb, "_embed", AsyncMock(return_value=None))
    assert await fb.get_fewshot_examples(None, "some narrative") == []


@pytest.mark.asyncio
async def test_classify_injects_fewshot_block(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, str] = {}

    async def fake_gen(prompt: str, _schema: type, **_k: object) -> object:
        captured["prompt"] = prompt
        return b.BatchClassificationResult(classifications=[
            b.TransactionClassification(entry_id="1", category="other", confidence=0.5)
        ])

    monkeypatch.setattr(b, "generate_structured_content", fake_gen)
    entries = [{"entry_id": "1", "narrative": "n", "amount": 1.0, "transaction_type": "debit"}]
    await b._classify_via_gemini(entries, fewshot_block="## Learned corrections\n- \"x\" → payroll\n")
    assert "Learned corrections" in captured["prompt"]
