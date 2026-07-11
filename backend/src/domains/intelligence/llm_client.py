"""Back-compat facade over the provider-agnostic ``llm`` package.

The provider logic lives in :mod:`src.domains.intelligence.llm`: ``base``
(interface), ``openai_compat`` (the sole ``openai`` importer), ``provider``
(resilience/telemetry policy), ``failover`` (primary + backup), ``telemetry`` +
``pricing``. This module is the app's stable AI seam — ``generate_structured_content``,
``generate_text_content``, ``generate_vision_content``, ``generate_vision_text_content``,
``generate_chat_content``, ``generate_embedding``, ``observe_llm_call``,
``agent_context``, ``LLMUnavailableError``, the re-exported metric collectors —
so agents/workers/services import from here and never touch a vendor SDK.

``get_llm_client`` assembles a Fireworks (Gemma 4) primary with an always-warm
Featherless backup; the agent call sites that use the ``generate_*`` helpers need
no edits when the provider set changes.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel

# Re-exported metric collectors (referenced as ``llm_client.AGENT_LLM_*`` by the
# observability tests and Agent E).
from src.core.metrics import (
    AGENT_LLM_CALLS as AGENT_LLM_CALLS,
)
from src.core.metrics import (
    AGENT_LLM_COST_USD as AGENT_LLM_COST_USD,
)
from src.core.metrics import (
    AGENT_LLM_LATENCY as AGENT_LLM_LATENCY,
)
from src.core.metrics import (
    AGENT_LLM_PROCESSING as AGENT_LLM_PROCESSING,
)
from src.core.metrics import (
    AGENT_LLM_TOKENS as AGENT_LLM_TOKENS,
)
from src.core.config import settings
from src.core.metrics import (
    LLM_TIMEOUT_COUNTER as LLM_TIMEOUT_COUNTER,
)
from src.domains.intelligence.llm.base import (
    BaseLLMClient,
)
from src.domains.intelligence.llm.base import (
    ChatCompletion as ChatCompletion,  # noqa: F401 — public re-export
)
from src.domains.intelligence.llm.base import (
    ChatTurn as ChatTurn,  # noqa: F401 — public re-export
)
from src.domains.intelligence.llm.failover import (
    FailoverLLMClient,
)
from src.domains.intelligence.llm.openai_compat import (
    ProviderSpec,
)
from src.domains.intelligence.llm.provider import (
    LLMUnavailableError as LLMUnavailableError,  # noqa: F401 — public re-export
)
from src.domains.intelligence.llm.provider import (
    OpenAICompatLLMClient,
)

# Telemetry helpers — re-exported for back-compat.
from src.domains.intelligence.llm.telemetry import (
    agent_context as agent_context,
)
from src.domains.intelligence.llm.telemetry import (
    current_agent_id as current_agent_id,
)
from src.domains.intelligence.llm.telemetry import (
    observe_llm_call as observe_llm_call,
)

# ---------------------------------------------------------------------------
# Provider selection
# ---------------------------------------------------------------------------

_provider: BaseLLMClient | None = None


def _build_client() -> BaseLLMClient:
    """Assemble the failover client: Fireworks primary + optional Featherless backup.

    The primary runs Gemma 4 on a dedicated (scale-to-zero) Fireworks deployment
    using strict ``json_schema`` structured output. When ``FEATHERLESS_API_KEY`` is
    set, an always-warm Featherless backup of the same Gemma 4 family is attached;
    it uses ``json_object`` structured output (Featherless does not enforce
    ``json_schema``). Leave the key blank for a Fireworks-only (no-failover) setup.
    """
    primary = OpenAICompatLLMClient(
        ProviderSpec(
            name="fireworks",
            api_key=settings.FIREWORKS_API_KEY,
            base_url=settings.LLM_API_BASE,
            model=settings.LLM_MODEL,
            structured_mode="json_schema",
            embedding_model=settings.EMBEDDING_MODEL,
            embedding_dimensions=settings.EMBEDDING_DIMENSIONS,
        )
    )
    backup: BaseLLMClient | None = None
    if settings.FEATHERLESS_API_KEY:
        backup = OpenAICompatLLMClient(
            ProviderSpec(
                name="featherless",
                api_key=settings.FEATHERLESS_API_KEY,
                base_url=settings.FEATHERLESS_API_BASE,
                model=settings.FEATHERLESS_MODEL,
                structured_mode="json_object",
                embedding_model=None,
            )
        )
    return FailoverLLMClient(primary, backup)


def get_llm_client() -> BaseLLMClient:
    """Return the configured LLM client (module-level singleton)."""
    global _provider
    if _provider is None:
        _provider = _build_client()
    return _provider


# ---------------------------------------------------------------------------
# Public async helpers (provider-agnostic)
# ---------------------------------------------------------------------------

async def generate_structured_content[T: BaseModel](
    prompt: str, response_schema: type[T], *, temperature: float | None = None
) -> T:
    """Call the configured LLM with native structured-output mode.

    Raises:
        LLMUnavailableError — on timeout or exhausted retry budget. LangGraph
            nodes should catch this via ``llm_degraded_node_result()``.
    """
    return await get_llm_client().generate_structured(
        prompt, response_schema, temperature=temperature
    )


async def generate_text_content(prompt: str, *, temperature: float | None = None) -> str:
    """Call the configured LLM for free-form text.

    Raises:
        LLMUnavailableError — on timeout or exhausted retry budget.
    """
    return await get_llm_client().generate_text(prompt, temperature=temperature)


async def generate_vision_content[T: BaseModel](
    prompt: str,
    *,
    image_bytes: bytes,
    mime_type: str,
    response_schema: type[T],
    temperature: float | None = None,
    model: str | None = None,
) -> T:
    """Call the configured LLM with an image + prompt → structured output.

    ``model`` overrides the default vision model (higher-fidelity re-scan, S6-6).

    Raises:
        LLMUnavailableError — on timeout or exhausted retry budget.
    """
    return await get_llm_client().generate_vision_structured(
        prompt,
        image_bytes=image_bytes,
        mime_type=mime_type,
        response_schema=response_schema,
        temperature=temperature,
        model=model,
    )


async def generate_vision_text_content(
    prompt: str,
    *,
    image_bytes: bytes,
    mime_type: str,
    temperature: float | None = None,
    model: str | None = None,
) -> str:
    """Call the configured LLM with an image + prompt → free-form text (e.g. OCR).

    Raises:
        LLMUnavailableError — on timeout or exhausted retry budget.
    """
    return await get_llm_client().generate_vision_text(
        prompt,
        image_bytes=image_bytes,
        mime_type=mime_type,
        temperature=temperature,
        model=model,
    )


async def generate_chat_content(
    messages: list[ChatTurn], *, system: str | None = None, max_tokens: int
) -> ChatCompletion:
    """Call the configured LLM for a role-based multi-turn conversation.

    Raises:
        LLMUnavailableError — on timeout or exhausted retry budget.
    """
    return await get_llm_client().generate_chat(
        messages, system=system, max_tokens=max_tokens
    )


async def generate_embedding(
    text: str,
    *,
    task_type: str | None = None,
    output_dimensionality: int | None = None,
) -> list[float]:
    """Return the embedding vector for ``text`` from the configured provider.

    Raises:
        LLMUnavailableError — on timeout or exhausted retry budget.
    """
    return await get_llm_client().embed(
        text, task_type=task_type, output_dimensionality=output_dimensionality
    )


# ---------------------------------------------------------------------------
# Graceful-degradation helpers
# ---------------------------------------------------------------------------

_DEGRADED_AI_RESPONSE: dict[str, Any] = {
    "status": "degraded_ai",
    "message": "AI service temporarily unavailable",
}


def llm_degraded_node_result(state: dict[str, Any]) -> dict[str, Any]:
    """Return a safe LangGraph state update when the LLM circuit breaker trips."""
    return {
        "error_messages": ["AI service temporarily unavailable — LLM circuit breaker tripped"],
        "context": {
            **state.get("context", {}),
            "llm_degraded": _DEGRADED_AI_RESPONSE,
        },
    }
