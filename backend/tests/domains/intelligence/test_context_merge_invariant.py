"""A2A P3 — merge-safe context reducer + minimal-diff write invariant.

Three concerns:

1. ``merge_context`` — the per-key reducer that replaces last-write-wins on
   ``OrchestratorState.context`` so parallel-stage agents don't clobber.
2. ``write_keys`` — each agent's owned key set is a superset of its primary
   ``context_key`` and **disjoint** across agents (the property that makes the
   shallow merge conflict-free).
3. A representative agent (J, the only DB-free node) actually returns a
   *minimal diff* — only its owned keys, not the full carried-forward context.

All hermetic — pure data plus one node invocation with Gemini mocked.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from src.domains.intelligence.agent_registry import AGENT_REGISTRY, write_keys
from src.domains.intelligence.agents.j_summarizer import make_j_summarizer_node
from src.domains.intelligence.schemas import (
    ExecutiveSummary,
    SummaryBullet,
    merge_context,
)

_ALL_AGENT_IDS = [d.agent_id for d in AGENT_REGISTRY]


# ── 1. merge_context reducer ──────────────────────────────────────────────────

def test_merge_disjoint_keys_is_union() -> None:
    assert merge_context({"forecast": 1}, {"audit_result": 2}) == {
        "forecast": 1,
        "audit_result": 2,
    }


def test_merge_right_wins_on_conflict() -> None:
    assert merge_context({"k": "old"}, {"k": "new"}) == {"k": "new"}


def test_merge_empty_right_preserves_left() -> None:
    left = {"forecast": 1, "audit_result": 2}
    assert merge_context(left, {}) == left


def test_merge_does_not_mutate_operands() -> None:
    left, right = {"a": 1}, {"b": 2}
    merge_context(left, right)
    assert left == {"a": 1} and right == {"b": 2}


def test_merge_simulates_two_parallel_agents() -> None:
    # Base accumulated context after stage 0's D and F both write their own key.
    base: dict[str, Any] = {"_route_origin": "g_reporter"}
    after_d = merge_context(base, {"forecast": {"x": 1}})
    after_both = merge_context(after_d, {"audit_result": {"y": 2}})
    assert after_both == {
        "_route_origin": "g_reporter",
        "forecast": {"x": 1},
        "audit_result": {"y": 2},
    }


# ── 2. write_keys ownership invariant ─────────────────────────────────────────

def test_write_keys_include_primary_context_key() -> None:
    for desc in AGENT_REGISTRY:
        assert desc.context_key in write_keys(desc.agent_id)


def test_write_keys_are_pairwise_disjoint() -> None:
    """No two agents may own the same context key — the merge-safety property."""
    seen: dict[str, str] = {}
    for agent_id in _ALL_AGENT_IDS:
        for key in write_keys(agent_id):
            assert key not in seen, (
                f"key {key!r} owned by both {seen[key]} and {agent_id}"
            )
            seen[key] = agent_id


def test_write_keys_unknown_agent_is_empty() -> None:
    assert write_keys("Z") == frozenset()


# ── 3. Minimal-diff return shape (representative node: J) ──────────────────────

def _state(context: dict[str, Any]) -> dict[str, Any]:
    return {
        "messages": [],
        "gen_ui_payloads": [],
        "error_messages": [],
        "next": "",
        "context": context,
        "session_id": "s1",
        "user_id": None,
        "mode": "insights",
    }


@pytest.mark.asyncio
async def test_j_summarizer_returns_only_owned_keys() -> None:
    node = make_j_summarizer_node()
    summary = ExecutiveSummary(bullets=[SummaryBullet(label="Cash Flow", text="Runway 4 months.")])
    # Seed the context with an upstream output *and* an unrelated input key; the
    # node must return neither — only its own executive-summary keys.
    seeded = {"forecast": {"horizon_days": 30}, "document_text": "unrelated input"}
    with patch(
        "src.domains.intelligence.agents.j_summarizer.generate_structured_content",
        new=AsyncMock(return_value=summary),
    ):
        result = await node(_state(seeded))

    returned_keys = set(result["context"])
    assert returned_keys <= write_keys("J"), f"J wrote foreign keys: {returned_keys - write_keys('J')}"
    assert returned_keys == {"executive_summary", "executive_summary_bullets"}
    # It must NOT carry the upstream/input keys forward (that's the reducer's job).
    assert "forecast" not in result["context"]
    assert "document_text" not in result["context"]
