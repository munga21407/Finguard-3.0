"""Gemini provider — the resilience/telemetry *policy* over :class:`BaseLLMClient`.

Owns the contract shared by every Gemini call, but not the calls themselves:
  - 30-second hard timeout per attempt via ``asyncio.wait_for``;
  - HTTP 429 / 5xx retried up to 4 times with exponential back-off (tenacity);
  - timeout / exhausted-budget / non-retryable errors surface as the
    provider-neutral :class:`LLMUnavailableError` so LangGraph nodes degrade
    instead of crashing;
  - per-call token/latency telemetry via ``observe_llm_call``.

The actual vendor SDK requests live in :class:`GeminiSdkClient`
(``llm.gemini_sdk``) — this module never imports ``google.genai``. It builds no
requests; it wraps the wrapper's calls with the cross-cutting concerns above and
parses the responses into the neutral return types of the interface.
"""
from __future__ import annotations

import asyncio
import logging
import math
import time
from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import BaseModel
from tenacity import (
    RetryError,
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from src.core.config import settings
from src.core.metrics import GEMINI_TIMEOUT_COUNTER
from src.domains.intelligence.llm.base import (
    BaseLLMClient,
    ChatCompletion,
    ChatTurn,
)
from src.domains.intelligence.llm.gemini_sdk import (
    GeminiSdkClient,
    SdkApiError,
    is_retryable_error,
)
from src.domains.intelligence.llm.telemetry import observe_llm_call

logger = logging.getLogger(__name__)

_LLM_TIMEOUT: float = 30.0


class LLMUnavailableError(RuntimeError):
    """Raised when the model is unreachable after the full retry budget / timeout."""


async def _guard[R](label: str, call: Callable[[], Awaitable[R]]) -> R:
    """Run a Gemini call, mapping timeout / exhausted-retry / API errors to
    the provider-neutral :class:`LLMUnavailableError`."""
    try:
        return await call()
    except TimeoutError as exc:
        GEMINI_TIMEOUT_COUNTER.inc()
        logger.error(
            "Gemini %s timed out — circuit breaker tripped",
            label,
            extra={"timeout_seconds": _LLM_TIMEOUT},
        )
        raise LLMUnavailableError(f"Gemini timeout after {_LLM_TIMEOUT}s: {exc}") from exc
    except (RetryError, SdkApiError) as exc:
        logger.error("Gemini %s failed after retries", label, exc_info=True)
        raise LLMUnavailableError(
            f"Gemini unavailable ({type(exc).__name__}): {exc}"
        ) from exc


def _retrying[R](fn: Callable[..., Awaitable[R]]) -> Callable[..., Awaitable[R]]:
    return retry(
        retry=retry_if_exception(is_retryable_error),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        stop=stop_after_attempt(4),
    )(fn)


def l2_normalize(vec: list[float]) -> list[float]:
    """Return the L2 (unit-norm) normalization of ``vec``.

    ``gemini-embedding-001`` only auto-normalizes at its native 3072 dims; when a
    smaller ``output_dimensionality`` is requested the returned vector is *not*
    unit-norm. Our pgvector indexes use ``vector_l2_ops`` with a fixed distance
    cutoff, so every embedding — doc side and query side — must live in the same
    normalized space or L2 distances become meaningless. Normalizing is a no-op
    for already-unit vectors, so this is safe to apply unconditionally.
    """
    norm = math.sqrt(sum(v * v for v in vec))
    if norm == 0.0:
        return vec
    return [v / norm for v in vec]


# ---------------------------------------------------------------------------
# Single-attempt calls: timeout + telemetry + parse around one wrapper call.
# Each is @_retrying-wrapped so transient 429/5xx retry with back-off.
# ---------------------------------------------------------------------------


@_retrying
async def _call_structured[T: BaseModel](
    sdk: GeminiSdkClient, prompt: str, response_schema: type[T], temperature: float | None
) -> T:
    _t0 = time.monotonic()
    response = await asyncio.wait_for(
        sdk.generate_structured(
            model=settings.GEMINI_MODEL,
            prompt=prompt,
            response_schema=response_schema,
            temperature=temperature,
        ),
        timeout=_LLM_TIMEOUT,
    )
    observe_llm_call(response, elapsed=time.monotonic() - _t0)
    return response_schema.model_validate_json(response.text or "")


@_retrying
async def _call_text(sdk: GeminiSdkClient, prompt: str, temperature: float | None) -> str:
    _t0 = time.monotonic()
    response = await asyncio.wait_for(
        sdk.generate_text(model=settings.GEMINI_MODEL, prompt=prompt, temperature=temperature),
        timeout=_LLM_TIMEOUT,
    )
    observe_llm_call(response, elapsed=time.monotonic() - _t0)
    return response.text or ""


@_retrying
async def _call_vision_structured[T: BaseModel](
    sdk: GeminiSdkClient,
    prompt: str,
    image_bytes: bytes,
    mime_type: str,
    response_schema: type[T],
    temperature: float | None,
    model: str | None,
) -> T:
    _t0 = time.monotonic()
    response = await asyncio.wait_for(
        sdk.generate_vision(
            model=model or settings.GEMINI_MODEL,
            prompt=prompt,
            image_bytes=image_bytes,
            mime_type=mime_type,
            temperature=temperature,
            response_schema=response_schema,
        ),
        timeout=_LLM_TIMEOUT,
    )
    observe_llm_call(response, elapsed=time.monotonic() - _t0)
    return response_schema.model_validate_json(response.text or "")


@_retrying
async def _call_vision_text(
    sdk: GeminiSdkClient,
    prompt: str,
    image_bytes: bytes,
    mime_type: str,
    temperature: float | None,
    model: str | None,
) -> str:
    _t0 = time.monotonic()
    response = await asyncio.wait_for(
        sdk.generate_vision(
            model=model or settings.GEMINI_MODEL,
            prompt=prompt,
            image_bytes=image_bytes,
            mime_type=mime_type,
            temperature=temperature,
            response_schema=None,
        ),
        timeout=_LLM_TIMEOUT,
    )
    observe_llm_call(response, elapsed=time.monotonic() - _t0)
    return response.text or ""


@_retrying
async def _call_chat(
    sdk: GeminiSdkClient, messages: list[ChatTurn], system: str | None, max_tokens: int
) -> ChatCompletion:
    _t0 = time.monotonic()
    response = await asyncio.wait_for(
        sdk.generate_chat(
            model=settings.GEMINI_MODEL,
            messages=[(m.role, m.content) for m in messages],
            system=system,
            max_tokens=max_tokens,
        ),
        timeout=_LLM_TIMEOUT,
    )
    observe_llm_call(response, elapsed=time.monotonic() - _t0)
    usage = getattr(response, "usage_metadata", None)
    return ChatCompletion(
        content=response.text or "",
        input_tokens=(getattr(usage, "prompt_token_count", 0) or 0) if usage else 0,
        output_tokens=(getattr(usage, "candidates_token_count", 0) or 0) if usage else 0,
    )


@_retrying
async def _call_embed(
    sdk: GeminiSdkClient,
    text: str,
    task_type: str | None,
    output_dimensionality: int | None,
) -> list[float]:
    """Single embedding attempt with a hard timeout. Returns the unit-norm vector."""
    response = await asyncio.wait_for(
        sdk.embed(
            model=settings.GEMINI_EMBEDDING_MODEL,
            text=text,
            task_type=task_type,
            output_dimensionality=output_dimensionality,
        ),
        timeout=_LLM_TIMEOUT,
    )
    embeddings: Any = response.embeddings
    return l2_normalize(list(embeddings[0].values))


class GeminiLLMClient(BaseLLMClient):
    """google-genai-backed provider (module-level singleton via get_llm_client)."""

    def __init__(self) -> None:
        self._sdk = GeminiSdkClient()

    async def generate_structured[T: BaseModel](
        self, prompt: str, response_schema: type[T], *, temperature: float | None = None
    ) -> T:
        return await _guard(
            "structured call",
            lambda: _call_structured(self._sdk, prompt, response_schema, temperature),
        )

    async def generate_text(self, prompt: str, *, temperature: float | None = None) -> str:
        return await _guard("text call", lambda: _call_text(self._sdk, prompt, temperature))

    async def generate_vision_structured[T: BaseModel](
        self,
        prompt: str,
        *,
        image_bytes: bytes,
        mime_type: str,
        response_schema: type[T],
        temperature: float | None = None,
        model: str | None = None,
    ) -> T:
        return await _guard(
            "vision call",
            lambda: _call_vision_structured(
                self._sdk, prompt, image_bytes, mime_type, response_schema, temperature, model
            ),
        )

    async def generate_vision_text(
        self,
        prompt: str,
        *,
        image_bytes: bytes,
        mime_type: str,
        temperature: float | None = None,
        model: str | None = None,
    ) -> str:
        return await _guard(
            "vision-text call",
            lambda: _call_vision_text(
                self._sdk, prompt, image_bytes, mime_type, temperature, model
            ),
        )

    async def generate_chat(
        self,
        messages: list[ChatTurn],
        *,
        system: str | None = None,
        max_tokens: int,
    ) -> ChatCompletion:
        return await _guard(
            "chat call", lambda: _call_chat(self._sdk, messages, system, max_tokens)
        )

    async def embed(
        self,
        text: str,
        *,
        task_type: str | None = None,
        output_dimensionality: int | None = None,
    ) -> list[float]:
        return await _guard(
            "embedding call",
            lambda: _call_embed(self._sdk, text, task_type, output_dimensionality),
        )
