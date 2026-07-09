"""A2A P1 (handoff provenance) + P5 (registry-generated agent table).

P1: ``make_handoff`` builds a valid typed envelope, and hub_writer emits one per
newly-produced agent output (deduped across planner stages, degraded-aware).
P5: the supervisor's AVAILABLE AGENTS table is generated from the registry, and
the planner's node map is registry-sourced — so adding an agent is one edit.

Hermetic: hub_writer's Mongo persistence is mocked.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from src.domains.intelligence import agent_registry
from src.domains.intelligence.agent_registry import (
    AGENT_REGISTRY,
    agent_node_names,
    make_handoff,
    supervisor_agent_table,
)
from src.domains.intelligence.agents.hub_writer import make_hub_writer_node
from src.domains.intelligence.schemas import AgentHandoff


def _state(context: dict[str, Any]) -> dict[str, Any]:
    return {
        "messages": [], "gen_ui_payloads": [], "error_messages": [], "handoffs": [],
        "next": "", "context": context, "session_id": "s1", "user_id": None,
        "mode": "insights",
    }


# ── P1: make_handoff envelope ─────────────────────────────────────────────────

def test_make_handoff_is_valid_envelope() -> None:
    h = make_handoff("G", status="ok")
    env = AgentHandoff.model_validate(h)          # round-trips through the schema
    assert env.agent_id == "G"
    assert env.context_key == "credit_strategy_result"
    assert env.status == "ok"
    assert env.produced_at                        # timestamp populated
    # depends_on carries G's declared consumes (forecast + audit_result).
    assert set(env.depends_on) == {"forecast", "audit_result"}


def test_make_handoff_unknown_agent_is_safe() -> None:
    env = AgentHandoff.model_validate(make_handoff("Z"))
    assert env.context_key == "" and env.depends_on == []


# ── P1: hub_writer emits provenance ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_hub_writer_emits_handoff_per_output() -> None:
    node = make_hub_writer_node()
    ctx = {
        "forecast": {"horizon_days": 30},
        "watchdog_analysis": {"summary": "ok", "degraded": True},
    }
    with patch(
        "src.domains.intelligence.agents.hub_writer.get_mongo_db"
    ), patch(
        "src.domains.intelligence.agents.hub_writer._persist_insight",
        new=AsyncMock(return_value="artifact-1"),
    ):
        out = await node(_state(ctx))

    handoffs = {h["agent_id"]: h for h in out.get("handoffs", [])}
    assert set(handoffs) == {"D", "E"}
    assert handoffs["D"]["status"] == "ok"
    assert handoffs["E"]["status"] == "degraded"      # inferred from payload flag
    # Dedup marker recorded for the next hub_writer pass.
    assert out["context"]["_handed_off"] == ["D", "E"]


@pytest.mark.asyncio
async def test_hub_writer_does_not_re_emit_already_handed_off() -> None:
    node = make_hub_writer_node()
    ctx = {"forecast": {}, "_handed_off": ["D"]}
    with patch(
        "src.domains.intelligence.agents.hub_writer.get_mongo_db"
    ), patch(
        "src.domains.intelligence.agents.hub_writer._persist_insight",
        new=AsyncMock(return_value=None),
    ):
        out = await node(_state(ctx))
    assert out.get("handoffs", []) == []              # D already handed off


# ── P5: registry-generated capability table ───────────────────────────────────

def test_agent_table_lists_every_agent() -> None:
    table = supervisor_agent_table()
    for desc in AGENT_REGISTRY:
        assert desc.node_name in table
        assert desc.description in table


def test_agent_table_is_sorted_and_well_formed() -> None:
    lines = supervisor_agent_table().splitlines()
    assert lines[0].startswith("| Agent") and "Responsibility" in lines[0]
    assert set(lines[1]) <= {"|", "-"}               # separator row
    node_cols = [line.split("|")[1].strip() for line in lines[2:]]
    assert node_cols == sorted(node_cols)
    assert node_cols == sorted(d.node_name for d in AGENT_REGISTRY)


def test_agent_table_tracks_registry_additions(monkeypatch: pytest.MonkeyPatch) -> None:
    import dataclasses
    extra = dataclasses.replace(
        AGENT_REGISTRY[0], agent_id="Z", context_key="z_out",
        node_name="z_agent", description="A brand new capability",
    )
    monkeypatch.setattr(agent_registry, "AGENT_REGISTRY", (*AGENT_REGISTRY, extra))
    table = supervisor_agent_table()
    assert "z_agent" in table and "A brand new capability" in table


def test_planner_node_map_is_registry_sourced() -> None:
    # The planner's dispatch map must match the registry (P5 single source).
    from src.domains.intelligence.agents.planner import _AGENT_TO_NODE
    assert agent_node_names() == _AGENT_TO_NODE
    assert set(_AGENT_TO_NODE) == {d.agent_id for d in AGENT_REGISTRY}
