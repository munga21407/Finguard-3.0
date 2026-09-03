"""Phase 2 (DeepSeek-harness-inspired roadmap) — "model-visible ⟺ reconstructible".

deepseek-harness treats this as a hard runtime-asserted invariant: "anything
that reaches a model request must be reconstructible from the session log."
Finguard has no single session log — provenance is split across LangGraph
checkpoints, MongoDB `intelligence_hub`, and Postgres `audit_logs`/`trust_log`
— and nothing asserts the property explicitly. This is the sharpest place to
check it: `hub_writer._compact_messages` (this session's own addition) prunes
older duplicate agent messages from *live* state via `RemoveMessage`, so this
is exactly the kind of change that could silently break reconstructability if
done carelessly.

The claim under test: a message removed from live state by compaction is
still recoverable by walking LangGraph's checkpoint history for that session
— i.e. compaction changes what the *next* model call sees, not what can be
proven happened. This holds only when checkpointing is enabled (see the
second test) — that precondition is exactly the kind of thing an implicit,
unasserted invariant lets slip unnoticed.

Hermetic: uses LangGraph's in-memory `MemorySaver`/no-checkpointer, a small
stand-in loop graph, and the real `hub_writer._compact_messages` /
`_COMPACT_THRESHOLD` — not a reimplementation — so a future change to the
actual compaction logic is what this test exercises.
"""
from __future__ import annotations

from typing import Annotated, Any, TypedDict

import pytest
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from src.domains.intelligence.agents.hub_writer import _compact_messages
from src.domains.intelligence.orchestrator import graph_config

_VISITS = 6  # 3 visits each for two alternating agent names — enough for
             # _compact_messages to find and prune a real duplicate-by-name
             # pair each hub run. (This test exercises the pruning algorithm
             # itself, reused as-is from hub_writer; the separate
             # len(messages) > _COMPACT_THRESHOLD gate that decides *whether*
             # to call it is already covered in test_agent_hub_writer.py.)


class _State(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    visits: int


async def _producer(state: _State) -> dict[str, Any]:
    n = state["visits"]
    # Alternate two agent names, like two real agents taking turns across hops.
    name = "d_forecaster" if n % 2 == 0 else "f_auditor"
    return {"messages": [AIMessage(content=f"pass-{n}", name=name)], "visits": n + 1}


async def _hub(state: _State) -> dict[str, Any]:
    # The real compaction logic under test — not a reimplementation.
    return {"messages": _compact_messages(state["messages"])}


def _route(state: _State) -> str:
    return "producer" if state["visits"] < _VISITS else END


def _build_loop_graph(checkpointer: MemorySaver | None) -> Any:
    workflow = StateGraph(_State)
    workflow.add_node("producer", _producer)
    workflow.add_node("hub", _hub)
    workflow.add_edge(START, "producer")
    workflow.add_edge("producer", "hub")
    workflow.add_conditional_edges("hub", _route, {"producer": "producer", END: END})
    return workflow.compile(checkpointer=checkpointer)


@pytest.mark.asyncio
async def test_compacted_messages_are_still_reconstructible_from_checkpoint_history() -> None:
    saver = MemorySaver()
    graph = _build_loop_graph(saver)
    config = graph_config("test-reconstructibility-1")

    final_state = await graph.ainvoke(
        {"messages": [HumanMessage(content="start")], "visits": 0}, config=config
    )

    # Compaction pruned the earlier duplicate visits for each agent name —
    # only the latest per name (and the original HumanMessage) survive live.
    live_contents = {m.content for m in final_state["messages"]}
    assert "pass-4" in live_contents      # latest d_forecaster visit survives
    assert "pass-5" in live_contents      # latest f_auditor visit survives
    assert "pass-0" not in live_contents  # earlier duplicates pruned from live state
    assert "pass-2" not in live_contents

    # But every message that ever existed is still recoverable by walking the
    # checkpoint history for this thread — the invariant under test.
    history = [snap async for snap in graph.aget_state_history(config)]
    assert len(history) > 1, "expected more than one checkpoint across the loop"

    ever_seen = {
        m.content for snap in history for m in snap.values.get("messages", [])
    }
    assert {"start", "pass-0", "pass-1", "pass-2", "pass-3", "pass-4", "pass-5"} <= ever_seen


@pytest.mark.asyncio
async def test_reconstructibility_requires_checkpointing_enabled() -> None:
    """Documents the invariant's real precondition: with checkpointing off
    (settings.LANGGRAPH_CHECKPOINTING_ENABLED=False in production —
    orchestrator.get_checkpointer() returns None), a message compaction
    prunes is genuinely, unrecoverably gone — there is no session log to
    fall back on. This is the gap deepseek-harness's own invariant would
    catch and Finguard currently would not."""
    graph = _build_loop_graph(checkpointer=None)
    config = graph_config("test-reconstructibility-2")

    await graph.ainvoke(
        {"messages": [HumanMessage(content="start")], "visits": 0}, config=config
    )

    with pytest.raises(ValueError, match="No checkpointer set"):
        [snap async for snap in graph.aget_state_history(config)]
