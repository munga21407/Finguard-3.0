"""Round-2 remediation R4 — the A2A planner through the *real* production
graph (``orchestrator.build_graph()``), not a stub graph.

``test_planner.py`` already proves the planner's staging/criticality/replan
logic in isolation and its Send/join/loop wiring against a hand-built stub
graph; ``test_agent_composite_payloads.py`` already proves each individual
agent node in isolation. Neither exercises ``orchestrator.build_graph()``
itself with the planner wired in — i.e. whether flipping
``A2A_PLANNER_ENABLED`` actually produces a graph that routes
supervisor → planner → parallel stage → hub_writer → planner → ... → END
correctly when it's someone's turn to decide whether to enable it. This is
that missing link, so the go/no-go decision in ``A2A_PROTOCOL.md`` §6 has a
real (if hermetic) exercise of the wiring to point to, not just its pieces.

Hermetic: agent node factories, hub_writer, the checkpointer, and the
supervisor's the model call are all stubbed — no real LLM/Mongo/Postgres.
"""
from __future__ import annotations

from typing import Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from src.domains.intelligence import orchestrator
from src.domains.intelligence.agent_registry import context_key_for
from src.domains.intelligence.agents import supervisor as sup

_STAGE0 = {"d_forecaster", "f_auditor"}  # D, F — independent, run in parallel
_STAGE1 = {"g_reporter"}                 # requires D (hard), folds in F (soft)
_STAGE2 = {"j_summarizer"}               # terminal executive summary


def _stub_agent_factory(agent_id: str, node_name: str, calls: list[str]):
    ck = context_key_for(agent_id)

    async def node(state: dict[str, Any]) -> dict[str, Any]:
        calls.append(node_name)
        return {
            "messages": [AIMessage(content=f"{node_name} ran", name=node_name)],
            "context": {ck: {"stub": True}},
        }

    return lambda: node


def _stub_hub_writer_factory(calls: list[str], artifact_ids: dict[str, str]):
    async def node(state: dict[str, Any]) -> dict[str, Any]:
        calls.append("hub_writer")
        # Stamp a fake artifact id per newly-produced context key, mirroring
        # the real hub_writer's per-output persistence (see hub_writer.py) —
        # proves this stage's outputs were actually handed to hub_writer, not
        # just computed and dropped.
        for key in ("forecast", "audit_result", "credit_strategy_result", "executive_summary"):
            if key in state["context"] and key not in artifact_ids:
                artifact_ids[key] = f"hub-{key}"
        return {"context": dict(state["context"])}

    return node


def _initial_state(session_id: str = "test-planner-e2e") -> dict[str, Any]:
    # Neutral phrase: no keyword-router match → reaches the LLM routing path
    # (matches test_planner.py's _routing_state()).
    return {
        "messages": [HumanMessage(content="prepare the quarterly board package")],
        "gen_ui_payloads": [],
        "error_messages": [],
        "next": "",
        "context": {},
        "session_id": session_id,
        "user_id": None,
        "mode": "insights",
    }


@pytest.fixture(autouse=True)
def _clear_supervisor_cache() -> Any:
    sup.reset_route_cache()
    yield
    sup.reset_route_cache()


@pytest.mark.asyncio
async def test_multi_target_intent_runs_dag_through_the_real_graph(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(orchestrator.settings, "A2A_PLANNER_ENABLED", True)

    # Supervisor's the-model decision: a multi-target board-pack request.
    async def _fixed_decision(_prompt: str, _schema: Any, **_k: Any) -> Any:
        return sup._SupervisorDecision(
            next="d_forecaster",
            reason="board pack needs forecast, audit, and credit strategy",
            targets=["d_forecaster", "f_auditor", "g_reporter"],
        )

    monkeypatch.setattr(sup, "generate_structured_content", _fixed_decision)

    calls: list[str] = []
    artifact_ids: dict[str, str] = {}
    for agent_id, node_name in [("D", "d_forecaster"), ("F", "f_auditor"), ("G", "g_reporter")]:
        monkeypatch.setattr(
            orchestrator,
            f"make_{node_name}_node",
            _stub_agent_factory(agent_id, node_name, calls),
        )
    # J (executive summary) always runs terminal — stub it too.
    monkeypatch.setattr(
        orchestrator,
        "make_j_summarizer_node",
        _stub_agent_factory("J", "j_summarizer", calls),
    )
    monkeypatch.setattr(
        orchestrator, "make_hub_writer_node", lambda: _stub_hub_writer_factory(calls, artifact_ids)
    )
    monkeypatch.setattr(orchestrator, "get_checkpointer", lambda: None)

    graph = orchestrator.build_graph()
    final_state = await graph.ainvoke(
        _initial_state(), config=orchestrator.graph_config("test-planner-e2e")
    )

    # ── Correct agents ran, correct order (stage 0 before stage 1 before J) ──
    stage0_positions = [calls.index(n) for n in ("d_forecaster", "f_auditor")]
    stage1_position = calls.index("g_reporter")
    stage2_position = calls.index("j_summarizer")
    assert max(stage0_positions) < stage1_position < stage2_position

    # ── hub_writer ran once per stage (3 stages: {D,F}, {G}, {J}) ────────────
    assert calls.count("hub_writer") == 3

    # ── Every output actually reached hub_writer (not just computed) ────────
    assert set(artifact_ids) == {
        "forecast", "audit_result", "credit_strategy_result", "executive_summary",
    }

    # ── Final state carries every agent's output ─────────────────────────────
    ctx = final_state["context"]
    for key in ("forecast", "audit_result", "credit_strategy_result", "executive_summary"):
        assert key in ctx, f"{key} missing from final context"

    # ── Graph actually terminated (planner drained the DAG, not the
    #     recursion ceiling) — no error_messages, no leftover planner state.
    assert final_state.get("error_messages") in (None, [])
    assert ctx.get("_planner_done") is True
