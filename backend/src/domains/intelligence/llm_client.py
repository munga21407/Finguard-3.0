"""
Gemini LLM client for the intelligence domain.

Provides a module-level singleton `Client` and the `generate_structured_content`
async helper that uses Gemini's native `response_schema` to guarantee
Pydantic-compliant structured outputs — no JSON prompt hacking.

Resilience:
  - Each Gemini call is wrapped in `asyncio.wait_for` with a 30-second hard
    timeout so a slow model never stalls the LangGraph supervisor indefinitely.
  - HTTP 429 (rate-limit) and 5xx (server) errors are retried up to 4 times
    with exponential back-off (2 s → 10 s) via tenacity.
  - When the retry budget or timeout is exhausted, `LLMUnavailableError` is
    raised so LangGraph nodes can catch it, append to `error_messages`, and
    route the supervisor to FINISH rather than hanging.
"""
from __future__ import annotations

import asyncio
import contextvars
import logging
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from google import genai
from google.genai import types
from google.genai.errors import APIError
from pydantic import BaseModel
from tenacity import (
    RetryError,
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from src.core.config import settings
from src.core.metrics import (
    AGENT_LLM_CALLS,
    AGENT_LLM_COST_USD,
    AGENT_LLM_LATENCY,
    AGENT_LLM_PROCESSING,
    AGENT_LLM_TOKENS,
    GEMINI_TIMEOUT_COUNTER,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Per-agent attribution for LLM observability.
#
# The graph wraps each node so this contextvar holds the running agent's name
# (see orchestrator._tracked).  Every Gemini call made inside a node therefore
# attributes its latency/tokens/cost to that agent on the /metrics dashboard
# without threading an agent_id argument through every call site.
# ---------------------------------------------------------------------------
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
) -> None:
    """Record per-agent LLM telemetry for one Gemini call.

    Centralises latency, token (prompt/completion), cost, and call-count metrics
    so every agent is covered uniformly.  ``elapsed`` is optional because callers
    that already record latency themselves (Agent E) can pass ``None`` to log
    only tokens/cost/calls and avoid double-counting the latency histogram.
    Tolerant of a missing ``usage_metadata`` (older responses / mocks).
    """
    aid = agent_id if agent_id is not None else current_agent_id()
    model = settings.GEMINI_MODEL

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
    cost = (
        prompt_tokens / 1_000_000 * settings.GEMINI_INPUT_USD_PER_MTOK
        + completion_tokens / 1_000_000 * settings.GEMINI_OUTPUT_USD_PER_MTOK
    )
    if cost:
        AGENT_LLM_COST_USD.labels(agent_id=aid, model=model).inc(cost)


_client: genai.Client | None = None

_LLM_TIMEOUT: float = 30.0
_RETRYABLE_HTTP_CODES: frozenset[int] = frozenset({429, 500, 502, 503, 504})


class LLMUnavailableError(RuntimeError):
    """Raised when Gemini is unreachable after the full retry budget / timeout."""


def _is_retryable(exc: BaseException) -> bool:
    """Return True only for rate-limit and transient server errors."""
    return isinstance(exc, APIError) and getattr(exc, "status_code", None) in _RETRYABLE_HTTP_CODES


def get_gemini_client() -> genai.Client:
    """Return (or lazily initialise) the module-level Gemini client."""
    global _client
    if _client is None:
        _client = genai.Client(api_key=settings.GEMINI_API_KEY)
    return _client


@retry(
    retry=retry_if_exception(_is_retryable),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    stop=stop_after_attempt(4),
)
async def _call_gemini[T: BaseModel](
    client: genai.Client,
    prompt: str,
    response_schema: type[T],
) -> T:
    """
    Single Gemini attempt wrapped in a 30-second hard timeout.

    Decorated with tenacity so HTTP 429 / 5xx responses are automatically
    retried with exponential back-off.  `asyncio.TimeoutError` is NOT retried
    — it propagates immediately to signal that the model is hung.
    """
    _t0 = time.monotonic()
    response = await asyncio.wait_for(
        client.aio.models.generate_content(
            model=settings.GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=response_schema,
            ),
        ),
        timeout=_LLM_TIMEOUT,
    )
    observe_llm_call(response, elapsed=time.monotonic() - _t0)
    return response_schema.model_validate_json(response.text or "")


# ---------------------------------------------------------------------------
# Graceful-degradation helpers
# ---------------------------------------------------------------------------

# Structured fallback payload returned by the convenience wrappers below when
# the circuit breaker trips.  Agents can match on status == "degraded_ai".
_DEGRADED_AI_RESPONSE: dict[str, Any] = {
    "status": "degraded_ai",
    "message": "AI service temporarily unavailable",
}

# Ready-made LangGraph node return value that preserves the error_messages
# accumulator without crashing the graph.  Agents catch LLMUnavailableError
# and return this instead of re-raising.
#
# Usage inside a node factory:
#     try:
#         result = await generate_structured_content(prompt, MySchema)
#     except LLMUnavailableError:
#         return llm_degraded_node_result(state)
#
def llm_degraded_node_result(state: dict[str, Any]) -> dict[str, Any]:
    """Return a safe LangGraph state update when the LLM circuit breaker trips."""
    return {
        "error_messages": ["AI service temporarily unavailable — LLM circuit breaker tripped"],
        "context": {
            **state.get("context", {}),
            "llm_degraded": _DEGRADED_AI_RESPONSE,
        },
    }


# ---------------------------------------------------------------------------
# Public async helpers
# ---------------------------------------------------------------------------

async def generate_structured_content[T: BaseModel](prompt: str, response_schema: type[T]) -> T:
    """
    Call Gemini with native structured-output mode.

    Enforces a 30-second hard timeout per attempt and retries HTTP 429 / 5xx
    responses with exponential back-off (up to 4 attempts).

    Raises:
        LLMUnavailableError — when the retry budget is exhausted, any attempt
            times out, or a non-retryable API error occurs.  LangGraph nodes
            should catch this via ``llm_degraded_node_result()`` and return a
            safe degraded state instead of crashing the graph.
    """
    client = get_gemini_client()
    try:
        return await _call_gemini(client, prompt, response_schema)
    except TimeoutError as exc:
        GEMINI_TIMEOUT_COUNTER.inc()
        logger.error(
            "Gemini structured call timed out — circuit breaker tripped",
            extra={"schema": response_schema.__name__, "timeout_seconds": _LLM_TIMEOUT},
        )
        raise LLMUnavailableError(
            f"Gemini timeout after {_LLM_TIMEOUT}s: {exc}"
        ) from exc
    except (RetryError, APIError) as exc:
        logger.error(
            "Gemini structured call failed after retries",
            exc_info=True,
            extra={"schema": response_schema.__name__},
        )
        raise LLMUnavailableError(
            f"Gemini unavailable ({type(exc).__name__}): {exc}"
        ) from exc


@retry(
    retry=retry_if_exception(_is_retryable),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    stop=stop_after_attempt(4),
)
async def _call_gemini_text(client: genai.Client, prompt: str) -> str:
    """
    Single free-form text attempt wrapped in a 30-second hard timeout.

    Mirrors ``_call_gemini`` but returns raw text instead of a Pydantic model.
    Used by agents that call Gemini for narrative/summary generation rather
    than structured JSON output.
    """
    _t0 = time.monotonic()
    response = await asyncio.wait_for(
        client.aio.models.generate_content(
            model=settings.GEMINI_MODEL,
            contents=prompt,
        ),
        timeout=_LLM_TIMEOUT,
    )
    observe_llm_call(response, elapsed=time.monotonic() - _t0)
    return response.text or ""


async def generate_text_content(prompt: str) -> str:
    """
    Call Gemini for free-form text with the same timeout / retry / observability
    guarantees as ``generate_structured_content``.

    Raises:
        LLMUnavailableError — on timeout or exhausted retry budget.
    """
    client = get_gemini_client()
    try:
        return await _call_gemini_text(client, prompt)
    except TimeoutError as exc:
        GEMINI_TIMEOUT_COUNTER.inc()
        logger.error(
            "Gemini text call timed out — circuit breaker tripped",
            extra={"timeout_seconds": _LLM_TIMEOUT},
        )
        raise LLMUnavailableError(
            f"Gemini timeout after {_LLM_TIMEOUT}s: {exc}"
        ) from exc
    except (RetryError, APIError) as exc:
        logger.error(
            "Gemini text call failed after retries",
            exc_info=True,
        )
        raise LLMUnavailableError(
            f"Gemini unavailable ({type(exc).__name__}): {exc}"
        ) from exc
