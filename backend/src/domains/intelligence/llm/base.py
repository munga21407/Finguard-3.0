"""Provider-agnostic LLM client interface.

Agents that only need "prompt in → structured/text out" depend on this ABC, not
on any vendor SDK, so the provider can be swapped (Gemini → Anthropic → OpenAI)
by registering a different implementation in ``llm_client.get_llm_client``.

``raw()`` is a deliberate escape hatch: several agents still use vendor-specific
features (vision, embeddings, native ``response_schema``, thinking budgets) that
are not yet part of this neutral interface.  They call ``raw()`` to reach the
underlying SDK client.  New code should prefer the abstract methods; migrating
the remaining ``raw()`` call sites is tracked as follow-up work.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel


class BaseLLMClient(ABC):
    @abstractmethod
    async def generate_structured[T: BaseModel](
        self, prompt: str, response_schema: type[T]
    ) -> T:
        """Return a schema-validated structured response for ``prompt``.

        Raises a provider-neutral ``LLMUnavailableError`` when the model is
        unreachable after the implementation's timeout / retry budget.
        """

    @abstractmethod
    async def generate_text(self, prompt: str) -> str:
        """Return a free-form text completion for ``prompt``."""

    @abstractmethod
    def raw(self) -> Any:
        """Return the underlying vendor SDK client (escape hatch).

        Used by call sites relying on provider-specific capabilities not yet
        exposed through this interface.
        """
