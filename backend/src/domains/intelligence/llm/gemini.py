"""Gemini implementation of :class:`BaseLLMClient`.

Owns the google-genai client construction plus the resilience contract shared by
every Gemini call:
  - 30-second hard timeout per attempt via ``asyncio.wait_for``;
  - HTTP 429 / 5xx retried up to 4 times with exponential back-off (tenacity);
  - timeout / exhausted-budget / non-retryable errors surface as the
    provider-neutral :class:`LLMUnavailableError` so LangGraph nodes degrade
    instead of crashing.

Capabilities: structured output, free-form text, multimodal (vision) structured
output, and embeddings — covering every call the agent graph makes.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
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
from src.core.metrics import GEMINI_TIMEOUT_COUNTER
from src.domains.intelligence.llm.base import BaseLLMClient
from src.domains.intelligence.llm.telemetry import observe_llm_call

logger = logging.getLogger(__name__)

_LLM_TIMEOUT: float = 30.0
_RETRYABLE_HTTP_CODES: frozenset[int] = frozenset({429, 500, 502, 503, 504})


class LLMUnavailableError(RuntimeError):
    """Raised when the model is unreachable after the full retry budget / timeout."""


def _is_retryable(exc: BaseException) -> bool:
    """Return True only for rate-limit and transient server errors."""
    return isinstance(exc, APIError) and getattr(exc, "status_code", None) in _RETRYABLE_HTTP_CODES


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
    except (RetryError, APIError) as exc:
        logger.error("Gemini %s failed after retries", label, exc_info=True)
        raise LLMUnavailableError(
            f"Gemini unavailable ({type(exc).__name__}): {exc}"
        ) from exc


def _structured_config(
    response_schema: type[BaseModel], temperature: float | None
) -> types.GenerateContentConfig:
    kwargs: dict[str, Any] = {
        "response_mime_type": "application/json",
        "response_schema": response_schema,
    }
    if temperature is not None:
        kwargs["temperature"] = temperature
    return types.GenerateContentConfig(**kwargs)


def _retrying[R](fn: Callable[..., Awaitable[R]]) -> Callable[..., Awaitable[R]]:
    return retry(
        retry=retry_if_exception(_is_retryable),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        stop=stop_after_attempt(4),
    )(fn)


@_retrying
async def _call_structured[T: BaseModel](
    client: genai.Client, prompt: str, response_schema: type[T], temperature: float | None
) -> T:
    """Single structured attempt wrapped in a 30-second hard timeout."""
    _t0 = time.monotonic()
    response = await asyncio.wait_for(
        client.aio.models.generate_content(
            model=settings.GEMINI_MODEL,
            contents=prompt,
            config=_structured_config(response_schema, temperature),
        ),
        timeout=_LLM_TIMEOUT,
    )
    observe_llm_call(response, elapsed=time.monotonic() - _t0)
    return response_schema.model_validate_json(response.text or "")


@_retrying
async def _call_text(client: genai.Client, prompt: str, temperature: float | None) -> str:
    """Single free-form text attempt wrapped in a 30-second hard timeout."""
    _t0 = time.monotonic()
    config = (
        types.GenerateContentConfig(temperature=temperature)
        if temperature is not None
        else None
    )
    response = await asyncio.wait_for(
        client.aio.models.generate_content(
            model=settings.GEMINI_MODEL,
            contents=prompt,
            config=config,
        ),
        timeout=_LLM_TIMEOUT,
    )
    observe_llm_call(response, elapsed=time.monotonic() - _t0)
    return response.text or ""


@_retrying
async def _call_vision[T: BaseModel](
    client: genai.Client,
    prompt: str,
    image_bytes: bytes,
    mime_type: str,
    response_schema: type[T],
    temperature: float | None,
    model: str | None = None,
) -> T:
    """Single multimodal (image + prompt → schema) attempt with a hard timeout."""
    _t0 = time.monotonic()
    response = await asyncio.wait_for(
        client.aio.models.generate_content(
            model=model or settings.GEMINI_MODEL,
            contents=[  # type: ignore[arg-type]
                types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
                types.Part.from_text(text=prompt),
            ],
            config=_structured_config(response_schema, temperature),
        ),
        timeout=_LLM_TIMEOUT,
    )
    observe_llm_call(response, elapsed=time.monotonic() - _t0)
    return response_schema.model_validate_json(response.text or "")


@_retrying
async def _call_embed(
    client: genai.Client,
    text: str,
    task_type: str | None,
    output_dimensionality: int | None,
) -> list[float]:
    """Single embedding attempt with a hard timeout. Returns the vector."""
    config_kwargs: dict[str, Any] = {}
    if task_type is not None:
        config_kwargs["task_type"] = task_type
    if output_dimensionality is not None:
        config_kwargs["output_dimensionality"] = output_dimensionality
    response = await asyncio.wait_for(
        client.aio.models.embed_content(
            model=settings.GEMINI_EMBEDDING_MODEL,
            contents=text,
            config=types.EmbedContentConfig(**config_kwargs) if config_kwargs else None,
        ),
        timeout=_LLM_TIMEOUT,
    )
    embeddings: Any = response.embeddings
    return list(embeddings[0].values)


class GeminiLLMClient(BaseLLMClient):
    """google-genai-backed LLM client (module-level singleton via get_llm_client)."""

    def __init__(self) -> None:
        self._client: genai.Client | None = None

    def raw(self) -> genai.Client:
        """Return (lazily initialising) the underlying google-genai client."""
        if self._client is None:
            self._client = genai.Client(api_key=settings.GEMINI_API_KEY)
        return self._client

    async def generate_structured[T: BaseModel](
        self, prompt: str, response_schema: type[T], *, temperature: float | None = None
    ) -> T:
        return await _guard(
            "structured call",
            lambda: _call_structured(self.raw(), prompt, response_schema, temperature),
        )

    async def generate_text(self, prompt: str, *, temperature: float | None = None) -> str:
        return await _guard("text call", lambda: _call_text(self.raw(), prompt, temperature))

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
            lambda: _call_vision(
                self.raw(), prompt, image_bytes, mime_type, response_schema, temperature, model
            ),
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
            lambda: _call_embed(self.raw(), text, task_type, output_dimensionality),
        )
