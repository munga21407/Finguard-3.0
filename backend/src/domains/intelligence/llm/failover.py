"""Failover LLM client — primary provider with an always-warm backup.

The primary (Fireworks) runs Gemma 4 on a dedicated deployment that scales to
zero: a cold start is ~3 minutes and surfaces as an immediate
:class:`LLMUnavailableError` (503 ``DEPLOYMENT_SCALING_UP`` is not retried, see
``provider``). Rather than make the user wait, this client catches that (and any
timeout / outage) and re-issues the call against the backup (Featherless), which
serves the same Gemma 4 model family serverlessly and is always warm.

Only when *both* providers fail does the neutral :class:`LLMUnavailableError`
propagate (so LangGraph nodes still degrade gracefully). Embeddings do **not**
fail over and do **not** necessarily go to ``primary`` — nomic only runs on
Fireworks (serverless, always warm, no cold start), so callers pass an explicit
``embedding_client`` when the generative primary is a provider that doesn't
serve embeddings (e.g. Gemini). ``embedding_client`` defaults to ``primary`` so
the common Fireworks-primary case needs nothing extra.
"""
from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import TypeVar

from pydantic import BaseModel

from src.core.metrics import LLM_FAILOVER_COUNTER
from src.domains.intelligence.llm.base import (
    BaseLLMClient,
    ChatCompletion,
    ChatTurn,
)
from src.domains.intelligence.llm.provider import LLMUnavailableError

logger = logging.getLogger(__name__)

_R = TypeVar("_R")


class FailoverLLMClient(BaseLLMClient):
    """Delegates to ``primary``; on :class:`LLMUnavailableError` tries ``backup``.

    With ``backup=None`` this is a transparent pass-through to the primary.
    """

    def __init__(
        self,
        primary: BaseLLMClient,
        backup: BaseLLMClient | None,
        *,
        embedding_client: BaseLLMClient | None = None,
    ) -> None:
        self._primary = primary
        self._backup = backup
        # Defaults to `primary` — correct whenever the generative primary also
        # serves embeddings (the Fireworks case). Callers whose primary doesn't
        # (Gemini) must pass a dedicated embeddings-capable client explicitly.
        self._embedding_client = embedding_client or primary

    async def _with_failover(
        self,
        capability: str,
        primary_call: Callable[[BaseLLMClient], Awaitable[_R]],
    ) -> _R:
        try:
            return await primary_call(self._primary)
        except LLMUnavailableError as primary_exc:
            if self._backup is None:
                raise
            logger.warning(
                "primary LLM unavailable for %s — failing over to backup: %s",
                capability,
                primary_exc,
            )
            try:
                result = await primary_call(self._backup)
            except LLMUnavailableError:
                LLM_FAILOVER_COUNTER.labels(capability=capability, result="backup_failed").inc()
                logger.error("backup LLM also unavailable for %s", capability)
                raise
            LLM_FAILOVER_COUNTER.labels(capability=capability, result="backup_ok").inc()
            return result

    async def generate_structured[T: BaseModel](
        self, prompt: str, response_schema: type[T], *, temperature: float | None = None
    ) -> T:
        return await self._with_failover(
            "structured",
            lambda c: c.generate_structured(prompt, response_schema, temperature=temperature),
        )

    async def generate_text(self, prompt: str, *, temperature: float | None = None) -> str:
        return await self._with_failover(
            "text", lambda c: c.generate_text(prompt, temperature=temperature)
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
        return await self._with_failover(
            "vision",
            lambda c: c.generate_vision_structured(
                prompt,
                image_bytes=image_bytes,
                mime_type=mime_type,
                response_schema=response_schema,
                temperature=temperature,
                model=model,
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
        return await self._with_failover(
            "vision-text",
            lambda c: c.generate_vision_text(
                prompt,
                image_bytes=image_bytes,
                mime_type=mime_type,
                temperature=temperature,
                model=model,
            ),
        )

    async def generate_chat(
        self,
        messages: list[ChatTurn],
        *,
        system: str | None = None,
        max_tokens: int,
    ) -> ChatCompletion:
        return await self._with_failover(
            "chat",
            lambda c: c.generate_chat(messages, system=system, max_tokens=max_tokens),
        )

    async def embed(
        self,
        text: str,
        *,
        task_type: str | None = None,
        output_dimensionality: int | None = None,
    ) -> list[float]:
        # Embeddings do not fail over, and do not necessarily go to `primary` —
        # see `_embedding_client` in __init__.
        return await self._embedding_client.embed(
            text, task_type=task_type, output_dimensionality=output_dimensionality
        )
