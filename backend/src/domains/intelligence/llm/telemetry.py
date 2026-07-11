"""Provider-neutral LLM observability: per-agent attribution + metric recording.

The graph wraps each node so ``_current_agent_id`` holds the running agent's
name (see orchestrator._tracked).  Every LLM call made inside a node therefore
attributes its latency/tokens/cost to that agent on the /metrics dashboard
without threading an agent_id argument through every call site.

Lives in the provider-neutral ``llm`` package so any ``BaseLLMClient``
implementation records telemetry the same way.  Cost is computed from the
model-keyed :mod:`pricing` table rather than a hardcoded rate.
"""
from __future__ import annotations

import contextvars
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from src.core.config import settings
from src.core.metrics import (
    AGENT_LLM_CALLS,
    AGENT_LLM_COST_USD,
    AGENT_LLM_LATENCY,
    AGENT_LLM_PROCESSING,
    AGENT_LLM_TOKENS,
)
from src.domains.intelligence.llm.pricing import cost_usd

_current_agent_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    "current_agent_id", default="unknown"
)


def current_agent_id() -> str:
    """The agent currently executing (``"unknown"`` outside a tracked node)."""
    return _current_agent_id.get()


@contextmanager
def agent_context(agent_id: str) -> Iterator[None]:
    """Attribute LLM calls made within the block to ``agent_id``."""
    token = _current_agent_id.set(agent_id)
    try:
        yield
    finally:
        _current_agent_id.reset(token)


def observe_llm_call(
    response: Any,
    *,
    elapsed: float | None = None,
    agent_id: str | None = None,
    status: str = "success",
    model: str | None = None,
) -> None:
    """Record per-agent LLM telemetry for one model call.

    Centralises latency, token (prompt/completion), cost, and call-count metrics
    so every agent is covered uniformly.  ``elapsed`` is optional because callers
    that already record latency themselves (Agent E) can pass ``None`` to log
    only tokens/cost/calls and avoid double-counting the latency histogram.
    ``model`` labels the metric with the provider's actual model (the failover
    backup differs from the primary); it defaults to the configured primary.
    Tolerant of a missing ``usage_metadata`` (older responses / mocks).
    """
    aid = agent_id if agent_id is not None else current_agent_id()
    model = model if model is not None else settings.LLM_MODEL

    if elapsed is not None:
        AGENT_LLM_LATENCY.labels(agent=aid, model=model).observe(elapsed)
        AGENT_LLM_PROCESSING.labels(agent_id=aid, model=model).observe(elapsed)

    AGENT_LLM_CALLS.labels(agent_id=aid, model=model, status=status).inc()

    usage = getattr(response, "usage_metadata", None)
    if usage is None:
        return
    # Telemetry must never throw into the agent path: coerce to int and bail out
    # if the response carries non-numeric token counts (malformed reply / mock).
    try:
        prompt_tokens = int(getattr(usage, "prompt_token_count", 0) or 0)
        completion_tokens = int(getattr(usage, "candidates_token_count", 0) or 0)
    except (TypeError, ValueError):
        return
    if prompt_tokens:
        AGENT_LLM_TOKENS.labels(agent_id=aid, model=model, kind="prompt").inc(prompt_tokens)
    if completion_tokens:
        AGENT_LLM_TOKENS.labels(agent_id=aid, model=model, kind="completion").inc(
            completion_tokens
        )
    cost = cost_usd(model, prompt_tokens, completion_tokens)
    if cost:
        AGENT_LLM_COST_USD.labels(agent_id=aid, model=model).inc(cost)
