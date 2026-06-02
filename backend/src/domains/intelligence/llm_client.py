"""
Gemini LLM client for the intelligence domain.

Provides a module-level singleton `Client` and the `generate_structured_content`
async helper that uses Gemini's native `response_schema` to guarantee
Pydantic-compliant structured outputs — no JSON prompt hacking.
"""
from __future__ import annotations

from google import genai
from google.genai import types
from pydantic import BaseModel

from src.core.config import settings

_client: genai.Client | None = None


def get_gemini_client() -> genai.Client:
    """Return (or lazily initialise) the module-level Gemini client."""
    global _client
    if _client is None:
        _client = genai.Client(api_key=settings.GEMINI_API_KEY)
    return _client


async def generate_structured_content[T: BaseModel](prompt: str, response_schema: type[T]) -> T:
    """
    Call Gemini with native structured-output mode.

    Gemini guarantees the response matches `response_schema`; no fallback
    JSON parsing is required. Raises `google.genai.errors.APIError` on
    model/network failures (let callers handle).
    """
    client = get_gemini_client()
    response = await client.aio.models.generate_content(
        model=settings.GEMINI_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=response_schema,
        ),
    )
    return response_schema.model_validate_json(response.text or "")
