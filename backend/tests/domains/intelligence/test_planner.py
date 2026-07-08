"""A2A P4 — multi-domain planner: staging, criticality, replan, wiring, routing.

Coverage:
  * pure ``build_full_plan`` / ``resolve_stage`` (staging + criticality + idempotency);
  * the planner node's stage advancement and replan;
  * a compiled LangGraph with **stub** agents proving the real Send fan-out /
    join / stage loop / END wiring end-to-end (no Mongo/Gemini/DB);
  * the supervisor's flag-gated multi-target → planner routing.
"""
from __future__ import annotations

from typing import Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph import END, StateGraph

from src.domains.intelligence.agent_registry import context_key_for
from src.domains.intelligence.agents import supervisor as sup
from src.domains.intelligence.agents.planner import (
    _AGENT_TO_NODE,
    after_hub_writer,
    build_full_plan,
    make_planner_node,
    planner_dispatch,
    resolve_stage,
)
from src.domains.intelligence.schemas import OrchestratorState

_TRACKED = {"forecast", "audit_result", "credit_strategy_result", "executive_summary"}


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


# ── 1. build_full_plan ────────────────────────────────────────────────────────

def test_plan_appends_terminal_j() -> None:
    assert build_full_plan(["g_reporter"]) == [["D"], ["G"], ["J"]]


def test_plan_parallel_first_stage() -> None:
    # D and F independent → one parallel stage; G after; J terminal.
    plan = build_full_plan(["d_forecaster", "f_auditor", "g_reporter"])
    assert plan == [["D", "F"], ["G"], ["J"]]


def test_plan_empty_targets_is_just_summary() -> None:
    assert build_full_plan([]) == [["J"]]


def test_plan_ignores_unknown_nodes() -> None:
    assert build_full_plan(["not_a_node", "g_reporter"]) == [["D"], ["G"], ["J"]]


# ── 2. resolve_stage (criticality + idempotency) ──────────────────────────────

def test_resolve_runs_when_deps_present() -> None:
    res = resolve_stage(["G"], {"forecast": {}})
    assert res.run == ["G"] and res.skipped == []


def test_resolve_skips_missing_required_dep() -> None:
    res = resolve_stage(["G"], {})           # G requires forecast, absent
    assert res.run == []
    assert res.skipped[0][0] == "G" and "missing_required:forecast" in res.skipped[0][1]


def test_resolve_skips_already_produced() -> None:
    res = resolve_stage(["D"], {"forecast": {"done": True}})
    assert res.run == [] and res.skipped == [("D", "already_produced")]


def test_resolve_optional_dep_missing_still_runs() -> None:
    # G's audit_result dep is optional → absence does not gate G.
    res = resolve_stage(["G"], {"forecast": {}})
    assert res.run == ["G"]


# ── 3. planner node: advancement + replan ─────────────────────────────────────

@pytest.mark.asyncio
async def test_node_first_entry_dispatches_stage0() -> None:
    node = make_planner_node()
    out = await node(_state({"_planner_targets": ["d_forecaster", "f_auditor", "g_reporter"]}))
    ctx = out["context"]
    assert ctx["_plan"] == [["D", "F"], ["G"], ["J"]]
    assert ctx["_stage"] == 0
    assert set(ctx["_current_dispatch"]) == {"d_forecaster", "f_auditor"}


@pytest.mark.asyncio
async def test_node_drained_marks_done() -> None:
    node = make_planner_node()
    # Last real stage index is 2 (J); entering with _stage=2 advances past the end.
    ctx = {
        "_planner_targets": ["g_reporter"],
        "_plan": [["D"], ["G"], ["J"]],
        "_stage": 2,
        "forecast": {}, "credit_strategy_result": {}, "executive_summary": {},
    }
    out = await node(_state(ctx))
    assert out["context"]["_current_dispatch"] == []
    assert out["context"]["_planner_done"] is True


@pytest.mark.asyncio
async def test_node_replans_within_budget() -> None:
    node = make_planner_node()
    ctx = {
        "_planner_targets": ["g_reporter"],
        "_plan": [["D"], ["G"], ["J"]],
        "_stage": 2,
        "_replan_targets": ["f_auditor"],
        "forecast": {}, "credit_strategy_result": {}, "executive_summary": {},
    }
    out = await node(_state(ctx))
    c = out["context"]
    assert c["_replans_used"] == 1
    assert c["_replan_targets"] == []                    # consumed
    assert c["_current_dispatch"] == ["f_auditor"]       # only the new, un-produced agent


# ── 4. edge functions ─────────────────────────────────────────────────────────

def test_dispatch_returns_sends() -> None:
    sends = planner_dispatch(_state({"_current_dispatch": ["d_forecaster", "f_auditor"]}))
    assert [s.node for s in sends] == ["d_forecaster", "f_auditor"]


def test_dispatch_drained_routes_end() -> None:
    assert planner_dispatch(_state({"_current_dispatch": []})) == END


def test_after_hub_returns_planner_mid_dag() -> None:
    assert after_hub_writer(_state({"_plan": [["J"]]})) == "planner"


def test_after_hub_returns_supervisor_when_no_plan() -> None:
    assert after_hub_writer(_state({})) == "supervisor"


def test_after_hub_returns_supervisor_when_done() -> None:
    assert after_hub_writer(_state({"_plan": [["J"]], "_planner_done": True})) == "supervisor"


# ── 5. Compiled stub graph — real Send/join/loop wiring ───────────────────────

def _stub_agent(agent_id: str) -> Any:
    ck = context_key_for(agent_id)
    node_name = _AGENT_TO_NODE[agent_id]

    async def node(state: OrchestratorState) -> dict[str, Any]:
        # Record which tracked outputs already existed when this agent started —
        # parallel-stage agents see an identical pre-stage context (empty prior).
        prior = sorted(k for k in state["context"] if k in _TRACKED)
        return {
            "messages": [AIMessage(content=agent_id, name=node_name)],
            "context": {ck: {"prior": prior}},
        }

    return node


async def _stub_hub(_state: OrchestratorState) -> dict[str, Any]:
    return {}


def _build_stub_graph() -> Any:
    wf = StateGraph(OrchestratorState)
    wf.add_node("planner", make_planner_node())
    wf.add_node("hub_writer", _stub_hub)
    agents = ["D", "F", "G", "J"]
    for aid in agents:
        wf.add_node(_AGENT_TO_NODE[aid], _stub_agent(aid))
        wf.add_edge(_AGENT_TO_NODE[aid], "hub_writer")
    wf.set_entry_point("planner")
    wf.add_conditional_edges(
        "planner", planner_dispatch, [*[_AGENT_TO_NODE[a] for a in agents], END]
    )
    wf.add_conditional_edges(
        "hub_writer", after_hub_writer, {"planner": "planner", "supervisor": END}
    )
    return wf.compile()


@pytest.mark.asyncio
async def test_compiled_planner_runs_dag_in_stages() -> None:
    graph = _build_stub_graph()
    state = _state({"_planner_targets": ["d_forecaster", "f_auditor", "g_reporter"]})
    result = await graph.ainvoke(state)
    ctx = result["context"]

    # All four agents produced their output exactly once.
    for key in _TRACKED:
        assert key in ctx, f"{key} was never produced"

    # Stage 0: D and F ran in parallel → each saw an empty pre-stage context.
    assert ctx["forecast"]["prior"] == []
    assert ctx["audit_result"]["prior"] == []
    # Stage 1: G ran after D and F → saw both their outputs.
    assert ctx["credit_strategy_result"]["prior"] == ["audit_result", "forecast"]
    # Stage 2: J ran last → saw everything before it.
    assert ctx["executive_summary"]["prior"] == [
        "audit_result", "credit_strategy_result", "forecast"
    ]


# ── 6. Supervisor multi-target routing (flag-gated) ───────────────────────────

@pytest.fixture(autouse=True)
def _clear_cache() -> Any:
    sup.reset_route_cache()
    yield
    sup.reset_route_cache()


def _patch_decision(monkeypatch: pytest.MonkeyPatch, **kw: Any) -> None:
    async def _gen(_prompt: str, _schema: Any, **_k: Any) -> Any:
        return sup._SupervisorDecision(**kw)

    monkeypatch.setattr(sup, "generate_structured_content", _gen)


def _routing_state() -> dict[str, Any]:
    # Neutral phrase: no keyword-router match → reaches the Gemini path.
    return _state({}) | {"messages": [HumanMessage(content="prepare the quarterly board package")]}


@pytest.mark.asyncio
async def test_supervisor_routes_multi_target_to_planner(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sup.settings, "A2A_PLANNER_ENABLED", True)
    _patch_decision(
        monkeypatch,
        next="d_forecaster",
        reason="board pack",
        targets=["d_forecaster", "f_auditor", "g_reporter"],
    )
    out = await make_supervisor_node_result()
    assert out["next"] == "planner"
    assert out["context"]["_planner_targets"] == ["d_forecaster", "f_auditor", "g_reporter"]


@pytest.mark.asyncio
async def test_supervisor_ignores_targets_when_flag_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sup.settings, "A2A_PLANNER_ENABLED", False)
    _patch_decision(
        monkeypatch, next="d_forecaster", reason="x",
        targets=["d_forecaster", "f_auditor"],
    )
    out = await make_supervisor_node_result()
    assert out["next"] == "d_forecaster"
    assert "_planner_targets" not in out["context"]


@pytest.mark.asyncio
async def test_supervisor_single_target_not_planned(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sup.settings, "A2A_PLANNER_ENABLED", True)
    _patch_decision(monkeypatch, next="d_forecaster", reason="x", targets=["d_forecaster"])
    out = await make_supervisor_node_result()
    assert out["next"] == "d_forecaster"


async def make_supervisor_node_result() -> dict[str, Any]:
    node = sup.make_supervisor_node()
    return await node(_routing_state())
