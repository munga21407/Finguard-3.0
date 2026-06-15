"""
Deterministic trajectory eval for the Supervisor (CV-1 — gates CI).

Output evals (``test_agent_f_tax_evals.py``) prove the *numbers* are right.
This suite proves the agent took the *right steps*: that the supervisor's
routing **contract** holds regardless of what the LLM returns. It is fast, free,
and fully mocked — no network, no tokens — so it blocks the build like the other
deterministic evals.

What's pinned here:
  * a valid ``requested_agent`` short-circuits routing *without* an LLM call;
  * an out-of-allowlist ``requested_agent`` is ignored and falls through to the LLM;
  * a valid LLM decision is honoured;
  * a hallucinated/unknown LLM route can never escape the allowlist → FINISH;
  * any LLM error degrades to FINISH instead of crashing the graph.

The companion ``test_supervisor_routing_judge.py`` measures whether the *real*
model routes the golden ``ROUTING_CASES`` correctly — non-deterministic, so
nightly and non-blocking.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.messages import HumanMessage

from src.domains.intelligence.agents.supervisor import (
    VALID_NEXT,
    _SupervisorDecision,
    make_supervisor_node,
)
from tests.evals.datasets import ROUTING_CASES, RouteCase

# Patch target — the name as looked up inside the supervisor module.
_LLM = "src.domains.intelligence.agents.supervisor.generate_structured_content"


def _state(messages: list[Any], **context: Any) -> dict[str, Any]:
    """Build a minimal OrchestratorState-shaped dict for the node under test."""
    return {
        "messages": messages,
        "gen_ui_payloads": [],
        "error_messages": [],
        "next": "",
        "context": context,
        "session_id": "test-session",
        "user_id": None,
        "mode": "insights",
    }


@pytest.mark.asyncio
async def test_valid_requested_agent_short_circuits_without_llm() -> None:
    node = make_supervisor_node()
    with patch(_LLM, new=AsyncMock()) as mock_llm:
        out = await node(_state([HumanMessage(content="anything")], requested_agent="f_auditor"))
    assert out["next"] == "f_auditor"
    mock_llm.assert_not_called()  # initial route was known — no token spent


@pytest.mark.asyncio
async def test_out_of_allowlist_requested_agent_is_ignored() -> None:
    node = make_supervisor_node()
    decision = _SupervisorDecision(next="FINISH", reason="done")
    with patch(_LLM, new=AsyncMock(return_value=decision)) as mock_llm:
        out = await node(_state([HumanMessage(content="hi")], requested_agent="evil_agent"))
    mock_llm.assert_awaited_once()  # bogus short-circuit ignored → fell through to LLM
    assert out["next"] == "FINISH"


@pytest.mark.asyncio
async def test_valid_llm_decision_is_routed() -> None:
    node = make_supervisor_node()
    decision = _SupervisorDecision(next="f_auditor", reason="tax question")
    with patch(_LLM, new=AsyncMock(return_value=decision)):
        out = await node(_state([HumanMessage(content="what's my VAT?")]))
    assert out["next"] == "f_auditor"
    assert out["messages"][0].name == "supervisor"


@pytest.mark.asyncio
async def test_unknown_llm_route_cannot_escape_allowlist() -> None:
    node = make_supervisor_node()
    decision = _SupervisorDecision(next="ceo_agent", reason="invented a new agent")
    with patch(_LLM, new=AsyncMock(return_value=decision)):
        out = await node(_state([HumanMessage(content="hi")]))
    assert out["next"] == "FINISH"  # hallucinated route rejected, not forwarded


@pytest.mark.asyncio
async def test_llm_error_degrades_to_finish() -> None:
    node = make_supervisor_node()
    with patch(_LLM, new=AsyncMock(side_effect=RuntimeError("gemini down"))):
        out = await node(_state([HumanMessage(content="hi")]))
    assert out["next"] == "FINISH"  # never crash the graph on a routing failure


@pytest.mark.parametrize("case", ROUTING_CASES, ids=lambda c: c.id)
def test_routing_dataset_targets_are_valid_agents(case: RouteCase) -> None:
    """Every golden expectation must name a real, routable agent — guards the
    nightly judge from silently asserting against a typo'd/removed agent."""
    assert case.expected_agent in VALID_NEXT, case.note
