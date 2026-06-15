"""Gemini implementation of :class:`BaseLLMClient`.

Owns the google-genai client construction plus the resilience contract shared by
every Gemini call:
  - 30-second hard timeout per attempt via ``asyncio.wait_for``;
  - HTTP 429 / 5xx retried up to 4 times with exponential back-off (tenacity);
  - timeout / exhausted-budget / non-retryable errors surface as the
    provider-neutral :class:`LLMUnavailableError` so LangGraph nodes degrade
    instead of crashing.
"""
from __future__ import annotations

import asyncio
import logging
import time

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


@retry(
    retry=retry_if_exception(_is_retryable),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    stop=stop_after_attempt(4),
)
async def _call_structured[T: BaseModel](
    client: genai.Client, prompt: str, response_schema: type[T]
) -> T:
    """Single structured attempt wrapped in a 30-second hard timeout."""
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


@retry(
    retry=retry_if_exception(_is_retryable),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    stop=stop_after_attempt(4),
)
async def _call_text(client: genai.Client, prompt: str) -> str:
    """Single free-form text attempt wrapped in a 30-second hard timeout."""
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
        self, prompt: str, response_schema: type[T]
    ) -> T:
        try:
            return await _call_structured(self.raw(), prompt, response_schema)
        except TimeoutError as exc:
            GEMINI_TIMEOUT_COUNTER.inc()
            logger.error(
                "Gemini structured call timed out — circuit breaker tripped",
                extra={"schema": response_schema.__name__, "timeout_seconds": _LLM_TIMEOUT},
            )
            raise LLMUnavailableError(f"Gemini timeout after {_LLM_TIMEOUT}s: {exc}") from exc
        except (RetryError, APIError) as exc:
            logger.error(
                "Gemini structured call failed after retries",
                exc_info=True,
                extra={"schema": response_schema.__name__},
            )
            raise LLMUnavailableError(
                f"Gemini unavailable ({type(exc).__name__}): {exc}"
            ) from exc

    async def generate_text(self, prompt: str) -> str:
        try:
            return await _call_text(self.raw(), prompt)
        except TimeoutError as exc:
            GEMINI_TIMEOUT_COUNTER.inc()
            logger.error(
                "Gemini text call timed out — circuit breaker tripped",
                extra={"timeout_seconds": _LLM_TIMEOUT},
            )
            raise LLMUnavailableError(f"Gemini timeout after {_LLM_TIMEOUT}s: {exc}") from exc
        except (RetryError, APIError) as exc:
            logger.error("Gemini text call failed after retries", exc_info=True)
            raise LLMUnavailableError(
                f"Gemini unavailable ({type(exc).__name__}): {exc}"
            ) from exc
