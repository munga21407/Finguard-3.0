"""Replayability — LangGraph checkpointing resumes from the last completed node.

Hermetic: uses LangGraph's in-memory ``MemorySaver`` (no Postgres) against a
small stand-in ``StateGraph`` built the same way ``orchestrator.build_graph``
wires nodes (via ``graph_config`` for the run config), so what's under test is
this project's checkpointing wiring (thread_id = session_id, resume via
``input=None``) rather than the full 12-agent production graph and its LLM
dependencies.
"""
from __future__ import annotations

from typing import Annotated, Any, TypedDict

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from src.domains.intelligence.orchestrator import graph_config


class _State(TypedDict):
    calls: Annotated[list[str], lambda a, b: a + b]
    fail_step_two_once: bool


def _build_two_step_graph(saver: MemorySaver, counters: dict[str, int]) -> Any:
    async def step_one(state: _State) -> dict[str, Any]:
        counters["step_one"] += 1
        return {"calls": ["step_one"]}

    async def step_two(state: _State) -> dict[str, Any]:
        counters["step_two"] += 1
        if state.get("fail_step_two_once") and counters["step_two"] == 1:
            raise RuntimeError("simulated transient failure in step_two")
        return {"calls": ["step_two"]}

    workflow = StateGraph(_State)
    workflow.add_node("step_one", step_one)
    workflow.add_node("step_two", step_two)
    workflow.add_edge(START, "step_one")
    workflow.add_edge("step_one", "step_two")
    workflow.add_edge("step_two", END)
    return workflow.compile(checkpointer=saver)


@pytest.mark.asyncio
async def test_resume_skips_already_completed_node() -> None:
    saver = MemorySaver()
    counters = {"step_one": 0, "step_two": 0}
    graph = _build_two_step_graph(saver, counters)
    session_id = "test-session-resume-1"
    config = graph_config(session_id)

    with pytest.raises(RuntimeError, match="simulated transient failure"):
        await graph.ainvoke(
            {"calls": [], "fail_step_two_once": True}, config=config
        )

    assert counters["step_one"] == 1
    assert counters["step_two"] == 1  # failed attempt

    # Resume: same thread_id, no fresh input — LangGraph continues from the
    # last checkpoint (after step_one) instead of restarting at START.
    final_state = await graph.ainvoke(None, config=config)

    assert counters["step_one"] == 1  # NOT re-invoked
    assert counters["step_two"] == 2  # retried and succeeded
    assert final_state["calls"] == ["step_one", "step_two"]


@pytest.mark.asyncio
async def test_fresh_run_without_failure_executes_each_node_once() -> None:
    saver = MemorySaver()
    counters = {"step_one": 0, "step_two": 0}
    graph = _build_two_step_graph(saver, counters)
    config = graph_config("test-session-resume-2")

    final_state = await graph.ainvoke(
        {"calls": [], "fail_step_two_once": False}, config=config
    )

    assert counters == {"step_one": 1, "step_two": 1}
    assert final_state["calls"] == ["step_one", "step_two"]
