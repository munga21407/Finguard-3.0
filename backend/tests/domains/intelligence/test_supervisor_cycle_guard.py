"""Sprint 6 — S6-4 supervisor cycle guard.

A benign loop (Gemini keeps routing to the same agent that produces no new
output/context) must terminate gracefully at FINISH *before* the LangGraph
recursion ceiling, rather than raising a 508. All hermetic — the Gemini client
is monkeypatched to a fixed decision.
"""
from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from src.domains.intelligence.agents import supervisor as sup


@pytest.fixture(autouse=True)
def _clear_cache():
    sup.reset_route_cache()
    yield
    sup.reset_route_cache()


def _fixed_decision(node: str):
    async def _decide(*_a, **_k):
        return sup._SupervisorDecision(next=node, reason=f"go to {node}")
    return _decide


# ── progress signature ────────────────────────────────────────────────────────

def test_progress_signature_ignores_internal_keys() -> None:
    msgs = [HumanMessage(content="hi"), AIMessage(content="x", name="d_forecaster")]
    a = sup._progress_signature(msgs, {"forecast": {}, "_route_origin": "d_forecaster"})
    b = sup._progress_signature(msgs, {"forecast": {}, "_route_history": [["d", "s"]]})
    assert a == b  # only public keys + agent names count


def test_progress_signature_changes_on_new_agent_output() -> None:
    ctx = {"forecast": {}}
    before = sup._progress_signature([HumanMessage(content="hi")], ctx)
    after = sup._progress_signature(
        [HumanMessage(content="hi"), AIMessage(content="x", name="d_forecaster")], ctx
    )
    assert before != after


# ── node-level cycle break ──────────────────────────────────────────────────

# The Sprint-3 single-agent FINISH short-circuit terminates as soon as the
# routed agent has *run* (emits an AIMessage named after itself). The cycle
# guard is the defence-in-depth layer for the pathological case where an agent
# keeps getting routed but produces no detectable output/context — so these
# tests deliberately simulate an agent that never registers progress.

@pytest.mark.asyncio
async def test_stalled_loop_breaks_to_finish(monkeypatch: pytest.MonkeyPatch) -> None:
    """Gemini keeps picking d_forecaster but nothing new is produced → FINISH."""
    monkeypatch.setattr(sup, "generate_structured_content", _fixed_decision("d_forecaster"))
    node = sup.make_supervisor_node()

    # a_generator already ran (past the initial hop); the session is now stuck on
    # d_forecaster, which yields no new agent output or context each hop.
    messages: list = [
        HumanMessage(content="do a full multi-step analysis"),
        AIMessage(content="done", name="a_generator"),
    ]
    context: dict = {"extracted_invoice": {}, "_route_origin": "d_forecaster"}

    broke = False
    for _ in range(sup._MAX_STALLED_REPEATS + 3):
        out = await node({"messages": messages, "context": context, "mode": "insights"})
        context = out["context"]
        # Carry forward only the supervisor message — no progress is produced.
        messages = messages + out["messages"]
        if out["next"] == "FINISH":
            broke = True
            assert "cycle" in out["messages"][-1].content.lower()
            break

    assert broke, "cycle guard did not terminate the stalled loop"


@pytest.mark.asyncio
async def test_progress_resets_repeat_counter(monkeypatch: pytest.MonkeyPatch) -> None:
    """Re-routing to the same node is fine as long as it makes progress."""
    monkeypatch.setattr(sup, "generate_structured_content", _fixed_decision("d_forecaster"))
    node = sup.make_supervisor_node()

    messages: list = [
        HumanMessage(content="do a full multi-step analysis"),
        AIMessage(content="done", name="a_generator"),
    ]
    context: dict = {"extracted_invoice": {}, "_route_origin": "d_forecaster"}

    for i in range(sup._MAX_STALLED_REPEATS + 3):
        out = await node({"messages": messages, "context": context, "mode": "insights"})
        context = out["context"]
        assert out["next"] == "d_forecaster", f"should not break — progress made (iter {i})"
        messages = messages + out["messages"]
        # Each hop adds a *new* public context key → signature advances every time,
        # so the repeat counter never accumulates.
        context[f"forecast_{i}"] = {"val": i}
