"""Thin google-genai SDK wrapper — the ONLY module that imports the vendor SDK.

Each method translates provider-neutral arguments into a google-genai request and
returns the raw SDK response. It owns nothing else: no retries, no timeouts, no
telemetry, no error translation — those are *policy*, applied one layer up in
:mod:`src.domains.intelligence.llm.gemini`. Swapping vendors means writing a
sibling wrapper + provider; nothing above this file imports ``google.genai``.
"""
from __future__ import annotations

from typing import Any

from google import genai
from google.genai import types
from google.genai.errors import APIError
from pydantic import BaseModel

from src.core.config import settings

# Re-exported so the policy layer can trap/classify SDK failures without importing
# the vendor package itself — keeping google-genai confined to this module.
SdkApiError = APIError
_RETRYABLE_HTTP_CODES: frozenset[int] = frozenset({429, 500, 502, 503, 504})


def is_retryable_error(exc: BaseException) -> bool:
    """True only for rate-limit / transient server errors worth retrying."""
    return (
        isinstance(exc, APIError)
        and getattr(exc, "status_code", None) in _RETRYABLE_HTTP_CODES
    )


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


def _text_config(temperature: float | None) -> types.GenerateContentConfig | None:
    return (
        types.GenerateContentConfig(temperature=temperature)
        if temperature is not None
        else None
    )


class GeminiSdkClient:
    """Owns the ``genai.Client`` and performs the actual model calls.

    Methods return the raw google-genai response; the caller (the provider) reads
    ``.text`` / ``.usage_metadata`` and applies resilience + telemetry. Kept free
    of any cross-cutting concern so it stays a faithful, swappable adapter.
    """

    def __init__(self) -> None:
        self._client: genai.Client | None = None

    @property
    def client(self) -> genai.Client:
        """Lazily construct the SDK client (defers API-key read past import)."""
        if self._client is None:
            self._client = genai.Client(api_key=settings.GEMINI_API_KEY)
        return self._client

    async def generate_structured(
        self,
        *,
        model: str,
        prompt: str,
        response_schema: type[BaseModel],
        temperature: float | None,
    ) -> Any:
        return await self.client.aio.models.generate_content(
            model=model,
            contents=prompt,
            config=_structured_config(response_schema, temperature),
        )

    async def generate_text(
        self, *, model: str, prompt: str, temperature: float | None
    ) -> Any:
        return await self.client.aio.models.generate_content(
            model=model, contents=prompt, config=_text_config(temperature)
        )

    async def generate_vision(
        self,
        *,
        model: str,
        prompt: str,
        image_bytes: bytes,
        mime_type: str,
        temperature: float | None,
        response_schema: type[BaseModel] | None = None,
    ) -> Any:
        """Image + prompt → response. Structured when ``response_schema`` is given,
        otherwise a free-form text response."""
        config = (
            _structured_config(response_schema, temperature)
            if response_schema is not None
            else _text_config(temperature)
        )
        return await self.client.aio.models.generate_content(
            model=model,
            # google-genai stubs type ``contents`` with an invariant list union, so
            # a plain list[Part] is rejected even though it is valid at runtime.
            contents=[  # type: ignore[arg-type]
                types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
                types.Part.from_text(text=prompt),
            ],
            config=config,
        )

    async def generate_chat(
        self,
        *,
        model: str,
        messages: list[tuple[str, str]],
        system: str | None,
        max_tokens: int,
    ) -> Any:
        """Role-based multi-turn chat. ``messages`` is ``[(role, text), ...]`` with
        role ∈ {"user", "model"}."""
        contents = [
            types.Content(role=role, parts=[types.Part(text=text)])
            for role, text in messages
        ]
        config_kwargs: dict[str, Any] = {"max_output_tokens": max_tokens}
        if system:
            config_kwargs["system_instruction"] = system
        return await self.client.aio.models.generate_content(
            model=model,
            contents=contents,  # type: ignore[arg-type]
            config=types.GenerateContentConfig(**config_kwargs),
        )

    async def embed(
        self,
        *,
        model: str,
        text: str,
        task_type: str | None,
        output_dimensionality: int | None,
    ) -> Any:
        config_kwargs: dict[str, Any] = {}
        if task_type is not None:
            config_kwargs["task_type"] = task_type
        if output_dimensionality is not None:
            config_kwargs["output_dimensionality"] = output_dimensionality
        return await self.client.aio.models.embed_content(
            model=model,
            contents=text,
            config=types.EmbedContentConfig(**config_kwargs) if config_kwargs else None,
        )
