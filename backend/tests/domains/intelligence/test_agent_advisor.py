"""Unit tests for Agent H (Financial Advisor).

``_resolve_user_role`` decides the advice persona. The context-supplied role
takes precedence (lowercased) and an absent user resolves to the safe default
``"viewer"`` without a DB hit.

The node tests pin the GenUI wiring: the narrative lands in ``context["advice"]``
and only allow-listed widgets are appended to ``gen_ui_payloads`` (a hallucinated
``component_id`` is dropped, never forwarded to the render stream).
"""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from src.domains.intelligence.agents import h_advisor
from src.domains.intelligence.agents.h_advisor import _resolve_user_role, make_h_advisor_node
from src.domains.intelligence.schemas import AgentHOutput, GenUIPayload


@pytest.mark.asyncio
async def test_context_role_takes_precedence_and_is_lowercased() -> None:
    assert await _resolve_user_role(user_id="anything", ctx_role="ADMIN") == "admin"


@pytest.mark.asyncio
async def test_no_user_defaults_to_viewer() -> None:
    assert await _resolve_user_role(user_id=None, ctx_role=None) == "viewer"


def _state(role: str) -> dict[str, Any]:
    # user_role + crm_profile in context → the node makes no DB call (hermetic).
    return {
        "context": {"user_role": role, "crm_profile": {"name": "Acme Ltd"}},
        "mode": "insights",
        "user_id": None,
        "session_id": "s-1",
        "messages": [],
        "gen_ui_payloads": [],
        "error_messages": [],
        "next": "",
    }


@pytest.mark.asyncio
async def test_node_narrative_to_advice_and_widgets_filtered() -> None:
    fake = AgentHOutput(
        narrative_response="Maintain runway; defer non-essential spend.",
        ui_widgets=[
            GenUIPayload(
                component_id="SemiCircleGaugeCard",
                props={"title": "Budget", "value": 92},
                fallback_text="Budget at 92%.",
            ),
            GenUIPayload(
                component_id="HallucinatedWidget",
                props={},
                fallback_text="nope",
            ),
        ],
    )
    with patch.object(
        h_advisor, "generate_structured_content", new=AsyncMock(return_value=fake)
    ):
        out = await make_h_advisor_node()(_state("manager"))

    advice = out["context"]["advice"]
    # No upstream analyses in this state → Sprint-5 limited-data disclaimer is
    # prepended; the LLM narrative still flows through.
    assert "Maintain runway" in advice["narrative_response"]
    assert advice["data_completeness"] == "none"
    assert advice["overall_outlook"] == advice["narrative_response"]  # Agent J compat
    assert advice["advice_tier"] == "ACTIONABLE"  # manager → actionable

    widgets = out["gen_ui_payloads"]
    assert [w.component_id for w in widgets] == ["SemiCircleGaugeCard"]


@pytest.mark.asyncio
async def test_node_llm_failure_degrades_with_narrative_and_no_widgets() -> None:
    with patch.object(
        h_advisor,
        "generate_structured_content",
        new=AsyncMock(side_effect=RuntimeError("gemini down")),
    ):
        out = await make_h_advisor_node()(_state("viewer"))

    assert out["context"]["advice"]["narrative_response"]  # non-empty fallback
    assert out["context"]["advice"]["advice_tier"] == "SUMMARY"  # viewer → summary
    assert out["gen_ui_payloads"] == []


# ── S6-5: advice-liability guardrails ──────────────────────────────────────────

def _fake_out() -> AgentHOutput:
    return AgentHOutput(narrative_response="Move 15% into 91-day T-bills.", ui_widgets=[])


@pytest.mark.asyncio
async def test_actionable_advice_carries_disclaimer() -> None:
    with patch.object(
        h_advisor, "generate_structured_content", new=AsyncMock(return_value=_fake_out())
    ):
        out = await make_h_advisor_node()(_state("owner"))
    advice = out["context"]["advice"]
    assert advice["advice_tier"] == "ACTIONABLE"
    assert "not regulated financial" in advice["narrative_response"].lower()
    # Gate is off by default → advice is not held for review.
    assert advice["requires_review"] is False
    assert advice["review_status"] == "not_required"


@pytest.mark.asyncio
async def test_summary_tier_has_no_disclaimer_and_no_review() -> None:
    with patch.object(
        h_advisor, "generate_structured_content", new=AsyncMock(return_value=_fake_out())
    ):
        out = await make_h_advisor_node()(_state("viewer"))
    advice = out["context"]["advice"]
    assert advice["advice_tier"] == "SUMMARY"
    assert "not regulated financial" not in advice["narrative_response"].lower()
    assert advice["requires_review"] is False


@pytest.mark.asyncio
async def test_review_gate_flags_actionable_advice_pending() -> None:
    state = _state("manager")
    state["context"]["require_advice_review"] = True  # per-request opt-in
    with patch.object(
        h_advisor, "generate_structured_content", new=AsyncMock(return_value=_fake_out())
    ):
        out = await make_h_advisor_node()(state)
    advice = out["context"]["advice"]
    assert advice["requires_review"] is True
    assert advice["review_status"] == "pending_review"
    assert advice["narrative_response"].startswith("🔒")
    # Disclaimer still present at the tail even with the review notice at the head.
    assert "not regulated financial" in advice["narrative_response"].lower()


@pytest.mark.asyncio
async def test_review_gate_does_not_affect_summary_tier() -> None:
    state = _state("viewer")
    state["context"]["require_advice_review"] = True
    with patch.object(
        h_advisor, "generate_structured_content", new=AsyncMock(return_value=_fake_out())
    ):
        out = await make_h_advisor_node()(state)
    # Summary tier is directional, never held for review.
    assert out["context"]["advice"]["requires_review"] is False
