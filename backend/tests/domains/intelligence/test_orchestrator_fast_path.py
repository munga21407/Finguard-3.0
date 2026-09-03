"""Fast-path routing bypass — single-domain, read-only agents skip the
supervisor graph entirely (orchestrator.try_fast_path / build_fast_path_graph).

Hermetic: agent/hub_writer node factories and the checkpointer are stubbed so
no real LLM/DB calls happen — only the routing/graph-wiring behaviour is under
test here (agent_registry.read_only_route is exercised directly against the
real keyword table since that's pure data, not an external dependency).
"""
from __future__ import annotations

from typing import Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import MemorySaver

from src.domains.intelligence import orchestrator
from src.domains.intelligence.agent_registry import heuristic_route, read_only_route
from src.domains.intelligence.llm_client import current_agent_id


def _stub_agent_factory(name: str, seen: list[str]):
    async def node(state: dict[str, Any]) -> dict[str, Any]:
        seen.append(current_agent_id())
        return {"messages": [AIMessage(content=f"{name} output", name=name)]}
    return lambda: node


def _stub_hub_writer_factory(seen: list[str]):
    async def node(state: dict[str, Any]) -> dict[str, Any]:
        seen.append(current_agent_id())
        return {"context": {"hub_writer_ran": True}}
    return node


def _initial_state(intent: str, session_id: str = "test-fast-path") -> dict[str, Any]:
    return {
        "messages": [HumanMessage(content=intent)],
        "gen_ui_payloads": [],
        "error_messages": [],
        "next": "supervisor",
        "context": {},
        "session_id": session_id,
        "user_id": None,
        "mode": "insights",
    }


# ── agent_registry classification (no graph involved) ────────────────────────

def test_read_only_route_matches_tagged_agent() -> None:
    assert heuristic_route("what is my vat tax liability") == "f_auditor"
    assert read_only_route("what is my vat tax liability") == "f_auditor"


def test_read_only_route_rejects_non_read_only_match() -> None:
    # c_reconciler matches cleanly but is not tagged read_only — must not
    # silently fast-path a write-capable agent.
    assert heuristic_route("please reconcile the mpesa payments") == "c_reconciler"
    assert read_only_route("please reconcile the mpesa payments") is None


def test_read_only_route_rejects_ambiguous_intent() -> None:
    assert heuristic_route("reconcile the tax") is None
    assert read_only_route("reconcile the tax") is None


# ── try_fast_path against a stubbed fast-path graph ───────────────────────────

@pytest.mark.asyncio
async def test_single_keyword_read_only_query_takes_fast_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[str] = []
    monkeypatch.setitem(
        orchestrator._FAST_PATH_NODE_FACTORIES,
        "f_auditor",
        _stub_agent_factory("f_auditor", seen),
    )
    monkeypatch.setattr(
        orchestrator, "make_hub_writer_node", lambda: _stub_hub_writer_factory(seen)
    )
    monkeypatch.setattr(orchestrator, "get_checkpointer", lambda: None)

    state = _initial_state("what is my vat tax liability")
    final_state = await orchestrator.try_fast_path(state)

    assert final_state is not None
    names = [getattr(m, "name", None) for m in final_state["messages"]]
    assert [n for n in names if n] == ["f_auditor"]
    assert "supervisor" not in names
    # _tracked wrapped both nodes with the correct cost-attribution label.
    assert seen == ["f_auditor", "hub_writer"]


@pytest.mark.asyncio
async def test_ambiguous_query_falls_through_to_full_graph(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(orchestrator, "get_checkpointer", lambda: None)
    state = _initial_state("reconcile the tax")
    assert await orchestrator.try_fast_path(state) is None


@pytest.mark.asyncio
async def test_non_read_only_agent_keyword_does_not_fast_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(orchestrator, "get_checkpointer", lambda: None)
    state = _initial_state("please reconcile the mpesa payments")
    assert await orchestrator.try_fast_path(state) is None


@pytest.mark.asyncio
async def test_requested_agent_short_circuit_skips_fast_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """requested_agent is a different, existing short-circuit (honoured inside
    the supervisor node) — try_fast_path must defer to it, not race it."""
    monkeypatch.setattr(orchestrator, "get_checkpointer", lambda: None)
    state = _initial_state("what is my vat tax liability")
    state["context"] = {"requested_agent": "f_auditor"}
    assert await orchestrator.try_fast_path(state) is None


# ── checkpoint/resume parity for the fast-path graph ──────────────────────────

@pytest.mark.asyncio
async def test_fast_path_checkpoint_resume(monkeypatch: pytest.MonkeyPatch) -> None:
    counters = {"f_auditor": 0, "hub_writer": 0}

    def _flaky_hub_writer_factory():
        async def node(state: dict[str, Any]) -> dict[str, Any]:
            counters["hub_writer"] += 1
            if counters["hub_writer"] == 1:
                raise RuntimeError("simulated transient failure in hub_writer")
            return {"context": {"hub_writer_ran": True}}
        return node

    async def _agent_node(state: dict[str, Any]) -> dict[str, Any]:
        counters["f_auditor"] += 1
        return {"messages": [AIMessage(content="f_auditor output", name="f_auditor")]}

    saver = MemorySaver()
    monkeypatch.setitem(
        orchestrator._FAST_PATH_NODE_FACTORIES, "f_auditor", lambda: _agent_node
    )
    monkeypatch.setattr(orchestrator, "make_hub_writer_node", _flaky_hub_writer_factory)
    monkeypatch.setattr(orchestrator, "get_checkpointer", lambda: saver)

    session_id = "test-fast-path-resume"
    config = orchestrator.graph_config(session_id)
    graph = orchestrator.build_fast_path_graph("f_auditor")

    with pytest.raises(RuntimeError, match="simulated transient failure"):
        await graph.ainvoke(_initial_state("vat", session_id), config=config)

    assert counters == {"f_auditor": 1, "hub_writer": 1}

    # Resume: same thread_id, no fresh input — f_auditor is NOT re-invoked.
    final_state = await graph.ainvoke(None, config=config)

    assert counters == {"f_auditor": 1, "hub_writer": 2}
    assert final_state["context"]["hub_writer_ran"] is True
