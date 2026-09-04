"""Thin OpenAI-compatible SDK wrapper — the ONLY module that imports ``openai``.

One wrapper serves every OpenAI-compatible provider (Fireworks primary,
Featherless backup) via a :class:`ProviderSpec`. Each method translates
provider-neutral arguments into a chat/embeddings request and returns a small
neutral adapter (``LLMResponse``) exposing ``.text`` and ``.usage_metadata`` —
the exact shape the policy layer (:mod:`llm.provider`) and
``telemetry.observe_llm_call`` read — so nothing above this file touches a vendor
type. It owns no cross-cutting concern: no retries, timeouts, telemetry, or error
translation — those are *policy*, one layer up.

Provider-specific quirks handled here (all verified live — Fireworks/Featherless
per the ``fireworks-migration`` memory, Gemini per
``tests/evals/test_gemini_provider_smoke.py``):

* **Thinking mode off.** Gemma's reasoning mode is on by default and consumes the
  token budget, so free-form calls can return empty content. Every request sends
  ``chat_template_kwargs.enable_thinking = False``.
* **Structured output strategy** is per-provider. Fireworks supports strict
  ``json_schema`` constrained decoding; Featherless does not (it returns
  markdown-fenced, loosely-keyed JSON), so it uses ``json_object`` mode instead.
  Either way the schema is also appended to the prompt and markdown fences are
  stripped from the reply before validation.
"""
from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from typing import Any

import openai
from openai import AsyncOpenAI
from pydantic import BaseModel

# Re-exported so the policy layer can trap/classify SDK failures without importing
# the vendor package itself — keeping ``openai`` confined to this module.
SdkApiError = openai.APIError
_RETRYABLE_HTTP_CODES: frozenset[int] = frozenset({429, 500, 502, 504})  # 503 handled below

# Default completion budget for the non-chat paths (chat passes its own). Kept
# generous so narrative/report structured outputs are never truncated.
_DEFAULT_MAX_TOKENS = 8192

# Disable Gemma's thinking mode on every call (see module docstring). This is
# ProviderSpec.extra_body's default, so Fireworks/Featherless keep sending it
# unchanged. Gemini has no equivalent verified flag and doesn't need one —
# empty replies from swallowed reasoning were never observed against it live
# (test_gemini_provider_smoke.py) — so its spec overrides extra_body to {}.
_GEMMA_EXTRA_BODY: dict[str, Any] = {"chat_template_kwargs": {"enable_thinking": False}}

# nomic-embed-text-v1.5 requires a task-instruction prefix; without it retrieval
# quality degrades. The app only ever passes these two task types.
_EMBED_PREFIX: dict[str, str] = {
    "RETRIEVAL_DOCUMENT": "search_document: ",
    "RETRIEVAL_QUERY": "search_query: ",
}


@dataclass(frozen=True)
class ProviderSpec:
    """Static configuration for one OpenAI-compatible provider."""

    name: str  # "fireworks" | "featherless" — used in logs / telemetry
    api_key: str
    base_url: str
    model: str  # chat + vision model id
    structured_mode: str = "json_schema"  # or "json_object" (Featherless)
    embedding_model: str | None = None  # None → provider offers no embeddings
    embedding_dimensions: int | None = None
    # Extra vendor-specific request body merged into every call. Defaults to the
    # Gemma thinking-mode-off flag (Fireworks/Featherless); override per spec for
    # a provider with different quirks — see the module docstring.
    extra_body: dict[str, Any] = field(default_factory=lambda: dict(_GEMMA_EXTRA_BODY))


def is_retryable_error(exc: BaseException) -> bool:
    """True for rate-limit / transient server / connection errors worth retrying.

    A 503 ``DEPLOYMENT_SCALING_UP`` (dedicated-deployment cold start) is
    deliberately *not* retryable: it should propagate immediately so the failover
    client routes to the always-warm backup instead of blocking ~3 minutes.
    """
    if isinstance(exc, (openai.APITimeoutError, openai.APIConnectionError)):
        return True
    if not isinstance(exc, openai.APIStatusError):
        return False
    if exc.status_code == 503:
        return not is_scaling_up(exc)  # scale-up → fail fast to backup
    return exc.status_code in _RETRYABLE_HTTP_CODES


def is_scaling_up(exc: BaseException) -> bool:
    """True for a dedicated-deployment cold start (503 ``DEPLOYMENT_SCALING_UP``)."""
    if not isinstance(exc, openai.APIStatusError) or exc.status_code != 503:
        return False
    return "DEPLOYMENT_SCALING_UP" in str(exc) or "scaling up" in str(exc).lower()


# ---------------------------------------------------------------------------
# Neutral response adapter — mirrors the ``.text`` / ``.usage_metadata`` shape
# the policy + telemetry layers read, so they stay vendor-agnostic.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Usage:
    prompt_token_count: int
    candidates_token_count: int


@dataclass(frozen=True)
class LLMResponse:
    text: str | None
    usage_metadata: _Usage


def _adapt(resp: Any, *, strip_fences: bool = False) -> LLMResponse:
    """Translate an OpenAI ChatCompletion into the neutral response shape.

    ``content`` may be ``None`` (e.g. a length-truncated reply); callers guard it
    exactly as they guarded the old vendor ``.text``. ``strip_fences`` removes a
    ```json … ``` markdown wrapper (backup provider emits these around JSON).
    """
    choice = resp.choices[0]
    usage = getattr(resp, "usage", None)
    text = choice.message.content
    if strip_fences:
        text = _strip_json_fences(text)
    return LLMResponse(
        text=text,
        usage_metadata=_Usage(
            prompt_token_count=(getattr(usage, "prompt_tokens", 0) or 0) if usage else 0,
            candidates_token_count=(
                (getattr(usage, "completion_tokens", 0) or 0) if usage else 0
            ),
        ),
    )


def _strip_json_fences(text: str | None) -> str | None:
    """Strip a leading ```json / ``` fence and a trailing ``` from ``text``."""
    if not text:
        return text
    t = text.strip()
    if t.startswith("```"):
        nl = t.find("\n")
        t = t[nl + 1 :] if nl != -1 else t[3:]
    if t.endswith("```"):
        t = t[:-3]
    return t.strip()


def _schema_prompt(prompt: str, schema: dict[str, Any]) -> str:
    return f"{prompt}\n\nReturn ONLY JSON matching this schema:\n{json.dumps(schema)}"


class OpenAICompatSdkClient:
    """Owns the ``AsyncOpenAI`` client for one provider and makes the model calls.

    Methods return an :class:`LLMResponse` (generative) or ``list[float]``
    (embeddings); the caller (the provider policy) applies resilience + telemetry.
    """

    def __init__(self, spec: ProviderSpec) -> None:
        self.spec = spec
        self._client: AsyncOpenAI | None = None

    @property
    def client(self) -> AsyncOpenAI:
        """Lazily construct the SDK client (defers API-key read past import)."""
        if self._client is None:
            self._client = AsyncOpenAI(api_key=self.spec.api_key, base_url=self.spec.base_url)
        return self._client

    # -- structured-output request shaping (per-provider strategy) -----------

    def _structured_kwargs(
        self, response_schema: type[BaseModel], schema: dict[str, Any]
    ) -> dict[str, Any]:
        if self.spec.structured_mode == "json_object":
            return {"response_format": {"type": "json_object"}}
        return {
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": response_schema.__name__, "schema": schema},
            }
        }

    async def generate_structured(
        self,
        *,
        model: str | None,
        prompt: str,
        response_schema: type[BaseModel],
        temperature: float | None,
    ) -> LLMResponse:
        schema = response_schema.model_json_schema()
        kwargs: dict[str, Any] = {
            "model": model or self.spec.model,
            "messages": [{"role": "user", "content": _schema_prompt(prompt, schema)}],
            "max_tokens": _DEFAULT_MAX_TOKENS,
            "extra_body": self.spec.extra_body,
            **self._structured_kwargs(response_schema, schema),
        }
        if temperature is not None:
            kwargs["temperature"] = temperature
        return _adapt(await self.client.chat.completions.create(**kwargs), strip_fences=True)

    async def generate_text(
        self, *, model: str | None, prompt: str, temperature: float | None
    ) -> LLMResponse:
        kwargs: dict[str, Any] = {
            "model": model or self.spec.model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": _DEFAULT_MAX_TOKENS,
            "extra_body": self.spec.extra_body,
        }
        if temperature is not None:
            kwargs["temperature"] = temperature
        return _adapt(await self.client.chat.completions.create(**kwargs))

    async def generate_vision(
        self,
        *,
        model: str | None,
        prompt: str,
        image_bytes: bytes,
        mime_type: str,
        temperature: float | None,
        response_schema: type[BaseModel] | None = None,
    ) -> LLMResponse:
        """Image + prompt → response. Structured when ``response_schema`` is given,
        otherwise free-form text (e.g. OCR)."""
        data_uri = "data:" + mime_type + ";base64," + base64.b64encode(image_bytes).decode()
        text = prompt
        kwargs: dict[str, Any] = {
            "model": model or self.spec.model,
            "max_tokens": _DEFAULT_MAX_TOKENS,
            "extra_body": self.spec.extra_body,
        }
        structured = response_schema is not None
        if response_schema is not None:
            schema = response_schema.model_json_schema()
            text = _schema_prompt(prompt, schema)
            kwargs.update(self._structured_kwargs(response_schema, schema))
        kwargs["messages"] = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": text},
                    {"type": "image_url", "image_url": {"url": data_uri}},
                ],
            }
        ]
        if temperature is not None:
            kwargs["temperature"] = temperature
        return _adapt(
            await self.client.chat.completions.create(**kwargs), strip_fences=structured
        )

    async def generate_chat(
        self,
        *,
        model: str | None,
        messages: list[tuple[str, str]],
        system: str | None,
        max_tokens: int,
    ) -> LLMResponse:
        """Role-based multi-turn chat. ``messages`` is ``[(role, text), ...]`` with
        role ∈ {"user", "model"}; "model" maps to the OpenAI "assistant" role."""
        msgs: list[dict[str, str]] = []
        if system:
            msgs.append({"role": "system", "content": system})
        for role, text in messages:
            msgs.append({"role": "assistant" if role == "model" else "user", "content": text})
        return _adapt(
            await self.client.chat.completions.create(
                model=model or self.spec.model,
                messages=msgs,
                max_tokens=max_tokens,
                extra_body=self.spec.extra_body,
            )
        )

    async def embed(
        self,
        *,
        model: str | None,
        text: str,
        task_type: str | None,
        output_dimensionality: int | None,
    ) -> list[float]:
        """Return the raw embedding vector for ``text`` (nomic prefix applied)."""
        if self.spec.embedding_model is None:
            raise RuntimeError(f"provider {self.spec.name!r} offers no embeddings")
        prefixed = _EMBED_PREFIX.get(task_type or "", "") + text
        dims = output_dimensionality or self.spec.embedding_dimensions
        resp = await self.client.embeddings.create(
            model=model or self.spec.embedding_model, input=prefixed, dimensions=dims
        )
        return list(resp.data[0].embedding)
