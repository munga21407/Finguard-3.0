"""Provider-agnostic LLM client interface.

Agents depend on this ABC, not on any vendor SDK, so the provider can be swapped
(Gemini → Anthropic → OpenAI) by registering a different implementation in
``llm_client.get_llm_client``. The interface covers the capabilities the agent
graph actually uses: structured output, free-form text, multimodal (vision)
structured output, and embeddings.

``raw()`` remains a deliberate escape hatch for genuinely vendor-specific paths
not modelled here (e.g. the multi-turn streaming chat in ``service.py`` with
roles + system instruction). The LangGraph agents and tools do not use it.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel


class BaseLLMClient(ABC):
    @abstractmethod
    async def generate_structured[T: BaseModel](
        self, prompt: str, response_schema: type[T], *, temperature: float | None = None
    ) -> T:
        """Return a schema-validated structured response for ``prompt``.

        Raises a provider-neutral ``LLMUnavailableError`` when the model is
        unreachable after the implementation's timeout / retry budget.
        """

    @abstractmethod
    async def generate_text(self, prompt: str, *, temperature: float | None = None) -> str:
        """Return a free-form text completion for ``prompt``."""

    @abstractmethod
    async def generate_vision_structured[T: BaseModel](
        self,
        prompt: str,
        *,
        image_bytes: bytes,
        mime_type: str,
        response_schema: type[T],
        temperature: float | None = None,
    ) -> T:
        """Return a schema-validated structured response over an image + prompt."""

    @abstractmethod
    async def embed(
        self,
        text: str,
        *,
        task_type: str | None = None,
        output_dimensionality: int | None = None,
    ) -> list[float]:
        """Return the embedding vector for ``text``."""

    @abstractmethod
    def raw(self) -> Any:
        """Return the underlying vendor SDK client (escape hatch).

        Used only by genuinely vendor-specific paths not modelled by the methods
        above (e.g. role-based multi-turn chat). Agents/tools must not use it.
        """
