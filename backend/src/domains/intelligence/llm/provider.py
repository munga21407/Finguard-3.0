"""OpenAI-compatible provider — the resilience/telemetry *policy* over
:class:`BaseLLMClient`, shared by every provider (Fireworks, Featherless).

Owns the contract shared by every model call, but not the calls themselves:
  - 30-second hard timeout per attempt via ``asyncio.wait_for``;
  - HTTP 429 / 5xx retried up to 4 times with exponential back-off (tenacity);
    a 503 ``DEPLOYMENT_SCALING_UP`` is *not* retried — it surfaces immediately so
    the failover client can route to the always-warm backup instead of blocking;
  - timeout / exhausted-budget / non-retryable errors surface as the
    provider-neutral :class:`LLMUnavailableError` (which the failover client
    catches to try the backup, and LangGraph nodes catch to degrade);
  - per-call token/latency telemetry via ``observe_llm_call``.

It never imports ``openai``: it wraps an :class:`OpenAICompatSdkClient` with the
cross-cutting concerns above and parses the neutral response into the interface's
return types.

Call chain (deliberately layered, not accidentally nested): ``llm_client``'s
facade functions call :class:`~src.domains.intelligence.llm.failover.FailoverLLMClient`
(cross-provider redundancy — primary vs. backup, tested in isolation in
``test_llm_provider.py``'s ``test_failover_*``), which calls this module's
:class:`OpenAICompatLLMClient` (the per-provider resilience policy above —
timeout/retry/telemetry, also independently tested here), which calls
:class:`~src.domains.intelligence.llm.openai_compat.OpenAICompatSdkClient` (the
vendor-SDK boundary — see that module's docstring: the ``openai`` SDK is
confined to a single wrapper and never leaks above :class:`BaseLLMClient`).
Each boundary is a distinct, separately-tested concern; collapsing them would
touch the single highest-traffic path in the app for a readability preference
with no runtime benefit, at the cost of the per-layer test isolation above.
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

from src.core.metrics import LLM_TIMEOUT_COUNTER
from src.domains.intelligence.llm.base import (
    BaseLLMClient,
    ChatCompletion,
    ChatTurn,
)
from src.domains.intelligence.llm.openai_compat import (
    OpenAICompatSdkClient,
    ProviderSpec,
    SdkApiError,
    is_retryable_error,
)
from src.domains.intelligence.llm.telemetry import observe_llm_call

logger = logging.getLogger(__name__)

_LLM_TIMEOUT: float = 30.0


class LLMUnavailableError(RuntimeError):
    """Raised when a provider is unreachable after its full retry budget / timeout."""


async def _guard[R](provider: str, label: str, call: Callable[[], Awaitable[R]]) -> R:
    """Run a model call, mapping timeout / exhausted-retry / API errors to the
    provider-neutral :class:`LLMUnavailableError`."""
    # A single provider failing is logged at WARNING (no traceback): it is an
    # expected, recoverable event — the failover client escalates to the backup,
    # and only raises (→ node degradation) when that also fails. Otherwise a
    # scaled-to-zero primary would spam ERROR tracebacks on every cold-start call.
    try:
        return await call()
    except TimeoutError as exc:
        LLM_TIMEOUT_COUNTER.inc()
        logger.warning(
            "%s %s timed out after %ss",
            provider,
            label,
            _LLM_TIMEOUT,
        )
        raise LLMUnavailableError(f"{provider} timeout after {_LLM_TIMEOUT}s: {exc}") from exc
    except (RetryError, SdkApiError) as exc:
        logger.warning("%s %s failed: %s", provider, label, exc)
        raise LLMUnavailableError(
            f"{provider} unavailable ({type(exc).__name__}): {exc}"
        ) from exc


def _retrying[R](fn: Callable[..., Awaitable[R]]) -> Callable[..., Awaitable[R]]:
    return retry(
        retry=retry_if_exception(is_retryable_error),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        stop=stop_after_attempt(4),
    )(fn)


def l2_normalize(vec: list[float]) -> list[float]:
    """Return the L2 (unit-norm) normalization of ``vec``.

    nomic-embed-text-v1.5 already returns unit-norm vectors at 768 dims, so this
    is a no-op safety net: our pgvector indexes use ``vector_l2_ops`` with a fixed
    distance cutoff, so every embedding — doc and query side — must share the same
    normalized space or L2 distances become meaningless.
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
    sdk: OpenAICompatSdkClient, prompt: str, response_schema: type[T], temperature: float | None
) -> T:
    _t0 = time.monotonic()
    response = await asyncio.wait_for(
        sdk.generate_structured(
            model=None, prompt=prompt, response_schema=response_schema, temperature=temperature
        ),
        timeout=_LLM_TIMEOUT,
    )
    observe_llm_call(response, elapsed=time.monotonic() - _t0, model=sdk.spec.model)
    return response_schema.model_validate_json(response.text or "")


@_retrying
async def _call_text(
    sdk: OpenAICompatSdkClient, prompt: str, temperature: float | None
) -> str:
    _t0 = time.monotonic()
    response = await asyncio.wait_for(
        sdk.generate_text(model=None, prompt=prompt, temperature=temperature),
        timeout=_LLM_TIMEOUT,
    )
    observe_llm_call(response, elapsed=time.monotonic() - _t0, model=sdk.spec.model)
    return response.text or ""


@_retrying
async def _call_vision_structured[T: BaseModel](
    sdk: OpenAICompatSdkClient,
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
            model=model,
            prompt=prompt,
            image_bytes=image_bytes,
            mime_type=mime_type,
            temperature=temperature,
            response_schema=response_schema,
        ),
        timeout=_LLM_TIMEOUT,
    )
    observe_llm_call(response, elapsed=time.monotonic() - _t0, model=model or sdk.spec.model)
    return response_schema.model_validate_json(response.text or "")


@_retrying
async def _call_vision_text(
    sdk: OpenAICompatSdkClient,
    prompt: str,
    image_bytes: bytes,
    mime_type: str,
    temperature: float | None,
    model: str | None,
) -> str:
    _t0 = time.monotonic()
    response = await asyncio.wait_for(
        sdk.generate_vision(
            model=model,
            prompt=prompt,
            image_bytes=image_bytes,
            mime_type=mime_type,
            temperature=temperature,
            response_schema=None,
        ),
        timeout=_LLM_TIMEOUT,
    )
    observe_llm_call(response, elapsed=time.monotonic() - _t0, model=model or sdk.spec.model)
    return response.text or ""


@_retrying
async def _call_chat(
    sdk: OpenAICompatSdkClient, messages: list[ChatTurn], system: str | None, max_tokens: int
) -> ChatCompletion:
    _t0 = time.monotonic()
    response = await asyncio.wait_for(
        sdk.generate_chat(
            model=None,
            messages=[(m.role, m.content) for m in messages],
            system=system,
            max_tokens=max_tokens,
        ),
        timeout=_LLM_TIMEOUT,
    )
    observe_llm_call(response, elapsed=time.monotonic() - _t0, model=sdk.spec.model)
    usage = response.usage_metadata
    return ChatCompletion(
        content=response.text or "",
        input_tokens=usage.prompt_token_count,
        output_tokens=usage.candidates_token_count,
    )


@_retrying
async def _call_embed(
    sdk: OpenAICompatSdkClient,
    text: str,
    task_type: str | None,
    output_dimensionality: int | None,
) -> list[float]:
    """Single embedding attempt with a hard timeout. Returns the unit-norm vector."""
    values = await asyncio.wait_for(
        sdk.embed(model=None, text=text, task_type=task_type, output_dimensionality=output_dimensionality),
        timeout=_LLM_TIMEOUT,
    )
    return l2_normalize(values)


class OpenAICompatLLMClient(BaseLLMClient):
    """One OpenAI-compatible provider (Fireworks or Featherless) with policy applied."""

    def __init__(self, spec: ProviderSpec) -> None:
        self.spec = spec
        self._sdk = OpenAICompatSdkClient(spec)

    @property
    def supports_embeddings(self) -> bool:
        return self.spec.embedding_model is not None

    async def generate_structured[T: BaseModel](
        self, prompt: str, response_schema: type[T], *, temperature: float | None = None
    ) -> T:
        return await _guard(
            self.spec.name,
            "structured call",
            lambda: _call_structured(self._sdk, prompt, response_schema, temperature),
        )

    async def generate_text(self, prompt: str, *, temperature: float | None = None) -> str:
        return await _guard(
            self.spec.name, "text call", lambda: _call_text(self._sdk, prompt, temperature)
        )

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
            self.spec.name,
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
            self.spec.name,
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
            self.spec.name,
            "chat call",
            lambda: _call_chat(self._sdk, messages, system, max_tokens),
        )

    async def embed(
        self,
        text: str,
        *,
        task_type: str | None = None,
        output_dimensionality: int | None = None,
    ) -> list[float]:
        return await _guard(
            self.spec.name,
            "embedding call",
            lambda: _call_embed(self._sdk, text, task_type, output_dimensionality),
        )
