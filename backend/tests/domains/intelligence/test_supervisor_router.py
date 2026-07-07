"""Sprint 3 — supervisor deterministic router + decision cache.

These verify the LLM routing call is skipped for clear single-agent intents,
for cached intents, and for the single-agent FINISH short-circuit. All hermetic:
the Gemini client is monkeypatched to explode if ever reached on these paths.
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


def _boom_factory(counter: dict[str, int]):
    async def _boom(*_a, **_k):
        counter["n"] += 1
        raise AssertionError("Gemini routing must not be called on a deterministic path")
    return _boom


# ── Pure heuristic ────────────────────────────────────────────────────────────

def test_heuristic_single_winner() -> None:
    assert sup._heuristic_route("please reconcile the mpesa payments") == "c_reconciler"
    assert sup._heuristic_route("what is my vat tax liability") == "f_auditor"
    assert sup._heuristic_route("generate invoice from this email") == "a_generator"


def test_heuristic_no_match_returns_none() -> None:
    assert sup._heuristic_route("hello, how are you today") is None


def test_heuristic_tie_defers_to_llm() -> None:
    # one c_reconciler keyword + one f_auditor keyword → tie → None
    assert sup._heuristic_route("reconcile the tax") is None


# ── Node short-circuits (no LLM) ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_node_heuristic_route_skips_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    counter = {"n": 0}
    monkeypatch.setattr(sup, "generate_structured_content", _boom_factory(counter))
    node = sup.make_supervisor_node()
    state = {"messages": [HumanMessage(content="reconcile mpesa payments")],
             "context": {}, "mode": "insights"}
    out = await node(state)
    assert out["next"] == "c_reconciler"
    assert out["context"]["_route_origin"] == "c_reconciler"
    assert counter["n"] == 0


@pytest.mark.asyncio
async def test_node_cache_hit_skips_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    counter = {"n": 0}
    monkeypatch.setattr(sup, "generate_structured_content", _boom_factory(counter))
    sup._cache_put("do the thing", "d_forecaster")
    node = sup.make_supervisor_node()
    state = {"messages": [HumanMessage(content="Do The Thing")],  # normalised → cache hit
             "context": {}, "mode": "insights"}
    out = await node(state)
    assert out["next"] == "d_forecaster"
    assert counter["n"] == 0


@pytest.mark.asyncio
async def test_single_agent_finish_short_circuit(monkeypatch: pytest.MonkeyPatch) -> None:
    counter = {"n": 0}
    monkeypatch.setattr(sup, "generate_structured_content", _boom_factory(counter))
    node = sup.make_supervisor_node()
    state = {
        "messages": [
            HumanMessage(content="reconcile mpesa"),
            AIMessage(content="done", name="c_reconciler"),
        ],
        "context": {"_route_origin": "c_reconciler"},
        "mode": "insights",
    }
    out = await node(state)
    assert out["next"] == "FINISH"
    assert counter["n"] == 0


def test_cache_eviction_bounded() -> None:
    last = sup._ROUTE_CACHE_MAX + 20
    for i in range(last):
        sup._cache_put(f"intent {i}", "d_forecaster")
    assert len(sup._INITIAL_ROUTE_CACHE) == sup._ROUTE_CACHE_MAX
    assert sup._cache_get("intent 0") is None                    # oldest evicted
    assert sup._cache_get(f"intent {last - 1}") == "d_forecaster"  # newest retained
