"""
Tests for per-agent LLM observability (token / cost / call metrics).

Verifies that `observe_llm_call`:
  * attributes tokens, cost, and call count to the agent set by `agent_context`;
  * splits prompt vs completion tokens and derives USD cost from configured
    list prices;
  * records latency only when `elapsed` is provided (so callers that already
    time the call — Agent E — can opt out and avoid double-counting);
  * tolerates a response with no `usage_metadata`.
"""
from __future__ import annotations

from types import SimpleNamespace

from prometheus_client import Counter, Histogram

from src.core.config import settings
from src.domains.intelligence import llm_client
from src.domains.intelligence.llm.pricing import cost_usd
from src.domains.intelligence.llm_client import (
    agent_context,
    current_agent_id,
    observe_llm_call,
)


def _sample(counter: Counter, **labels: str) -> float:
    """Read the current value of a labelled counter sample (0.0 if absent)."""
    return counter.labels(**labels)._value.get()


def _hist_count(hist: Histogram, **labels: str) -> float:
    return hist.labels(**labels)._sum.get()


def _resp(prompt: int, completion: int) -> SimpleNamespace:
    return SimpleNamespace(
        usage_metadata=SimpleNamespace(
            prompt_token_count=prompt,
            candidates_token_count=completion,
        )
    )


def test_agent_context_sets_and_resets() -> None:
    assert current_agent_id() == "unknown"
    with agent_context("f_auditor"):
        assert current_agent_id() == "f_auditor"
    assert current_agent_id() == "unknown"


def test_tokens_cost_and_calls_attributed_to_agent() -> None:
    model = settings.LLM_MODEL
    labels_prompt = dict(agent_id="d_forecaster", model=model, kind="prompt")
    labels_completion = dict(agent_id="d_forecaster", model=model, kind="completion")
    cost_labels = dict(agent_id="d_forecaster", model=model)
    call_labels = dict(agent_id="d_forecaster", model=model, status="success")

    p0 = _sample(llm_client.AGENT_LLM_TOKENS, **labels_prompt)
    c0 = _sample(llm_client.AGENT_LLM_TOKENS, **labels_completion)
    cost0 = _sample(llm_client.AGENT_LLM_COST_USD, **cost_labels)
    calls0 = _sample(llm_client.AGENT_LLM_CALLS, **call_labels)

    with agent_context("d_forecaster"):
        observe_llm_call(_resp(1000, 200), elapsed=0.5)

    assert _sample(llm_client.AGENT_LLM_TOKENS, **labels_prompt) == p0 + 1000
    assert _sample(llm_client.AGENT_LLM_TOKENS, **labels_completion) == c0 + 200
    assert _sample(llm_client.AGENT_LLM_CALLS, **call_labels) == calls0 + 1

    expected_cost = cost_usd(model, 1000, 200)
    assert _sample(llm_client.AGENT_LLM_COST_USD, **cost_labels) == cost0 + expected_cost


def test_elapsed_none_records_no_latency() -> None:
    """Agent E times its own call and passes elapsed=None — no double latency."""
    model = settings.LLM_MODEL
    before = _hist_count(llm_client.AGENT_LLM_PROCESSING, agent_id="e_watchdog", model=model)

    observe_llm_call(_resp(10, 5), elapsed=None, agent_id="e_watchdog")

    after = _hist_count(llm_client.AGENT_LLM_PROCESSING, agent_id="e_watchdog", model=model)
    assert after == before  # latency histogram untouched when elapsed is None


def test_missing_usage_metadata_is_tolerated() -> None:
    model = settings.LLM_MODEL
    call_labels = dict(agent_id="j_summarizer", model=model, status="success")
    calls0 = _sample(llm_client.AGENT_LLM_CALLS, **call_labels)

    # No usage_metadata attribute at all — must not raise, still counts the call.
    observe_llm_call(SimpleNamespace(), agent_id="j_summarizer")

    assert _sample(llm_client.AGENT_LLM_CALLS, **call_labels) == calls0 + 1
