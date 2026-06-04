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
import logging

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

logger = logging.getLogger(__name__)

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
    return response_schema.model_validate_json(response.text or "")


async def generate_structured_content[T: BaseModel](prompt: str, response_schema: type[T]) -> T:
    """
    Call Gemini with native structured-output mode.

    Enforces a 30-second hard timeout per attempt and retries HTTP 429 / 5xx
    responses with exponential back-off (up to 4 attempts).

    Raises:
        LLMUnavailableError — when the retry budget is exhausted, any attempt
            times out, or a non-retryable API error occurs.  LangGraph nodes
            should catch this, append a message to `error_messages`, and return
            a state that routes the supervisor to FINISH.
    """
    client = get_gemini_client()
    try:
        return await _call_gemini(client, prompt, response_schema)
    except (RetryError, asyncio.TimeoutError, APIError) as exc:
        logger.error(
            "Gemini structured call failed after retries/timeout",
            exc_info=True,
            extra={"schema": response_schema.__name__},
        )
        raise LLMUnavailableError(
            f"Gemini unavailable ({type(exc).__name__}): {exc}"
        ) from exc
