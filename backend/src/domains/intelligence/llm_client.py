"""Back-compat facade over the provider-agnostic ``llm`` package.

The Gemini-specific logic now lives in :mod:`src.domains.intelligence.llm`
(``base`` interface, ``gemini`` implementation, ``telemetry`` + ``pricing``).
This module preserves the original public surface — ``generate_structured_content``,
``generate_text_content``, ``get_gemini_client``, ``observe_llm_call``,
``agent_context``, ``LLMUnavailableError``, the re-exported metric collectors —
so existing agents and tests keep importing from here unchanged.

To swap providers, register a different :class:`BaseLLMClient` in
``get_llm_client`` (or wire it through settings); the agent call sites that use
the ``generate_*`` helpers need no edits.
"""
from __future__ import annotations

from typing import Any

from google import genai
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
from src.core.metrics import (
    GEMINI_TIMEOUT_COUNTER as GEMINI_TIMEOUT_COUNTER,
)
from src.domains.intelligence.llm.base import BaseLLMClient
from src.domains.intelligence.llm.gemini import (
    GeminiLLMClient,
)
from src.domains.intelligence.llm.gemini import (
    LLMUnavailableError as LLMUnavailableError,  # noqa: F401 — public re-export
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


def get_llm_client() -> BaseLLMClient:
    """Return the configured LLM client (module-level singleton).

    Swap the provider here (or behind a settings flag) to migrate off Gemini.
    """
    global _provider
    if _provider is None:
        _provider = GeminiLLMClient()
    return _provider


def get_gemini_client() -> genai.Client:
    """Return the underlying google-genai SDK client.

    Retained for the agents that still use provider-specific features (vision,
    embeddings, native ``response_schema``, thinking budgets) directly via
    ``client.aio.models``.  Prefer the ``generate_*`` helpers in new code.
    """
    return get_llm_client().raw()


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
) -> T:
    """Call the configured LLM with an image + prompt → structured output.

    Raises:
        LLMUnavailableError — on timeout or exhausted retry budget.
    """
    return await get_llm_client().generate_vision_structured(
        prompt,
        image_bytes=image_bytes,
        mime_type=mime_type,
        response_schema=response_schema,
        temperature=temperature,
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
