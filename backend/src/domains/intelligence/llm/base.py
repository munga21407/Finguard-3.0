"""Provider-agnostic LLM interface — the AI capability contract this app owns.

Agents, workers, and services depend on this ABC (and the ``llm_client`` facade
over it), never on any vendor SDK, so the provider can be swapped
(Gemini → Anthropic → OpenAI) by registering a different implementation in
``llm_client.get_llm_client``. The interface covers every capability the app
uses: structured output, free-form text, multimodal (vision) structured and text
output, role-based multi-turn chat, and embeddings.

There is deliberately no ``raw()`` escape hatch: the vendor SDK is confined to a
single wrapper module (``llm.gemini_sdk``) and never leaks above this contract.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from pydantic import BaseModel


@dataclass(frozen=True)
class ChatTurn:
    """One turn of a multi-turn conversation. ``role`` ∈ {"user", "model"}."""

    role: str
    content: str


@dataclass(frozen=True)
class ChatCompletion:
    """Provider-neutral result of a chat completion (no vendor types)."""

    content: str
    input_tokens: int
    output_tokens: int


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
        model: str | None = None,
    ) -> T:
        """Return a schema-validated structured response over an image + prompt.

        ``model`` overrides the provider's default vision model (used to re-scan
        a low-confidence receipt with a higher-fidelity model — S6-6).
        """

    @abstractmethod
    async def generate_vision_text(
        self,
        prompt: str,
        *,
        image_bytes: bytes,
        mime_type: str,
        temperature: float | None = None,
        model: str | None = None,
    ) -> str:
        """Return a free-form text response over an image + prompt (e.g. OCR)."""

    @abstractmethod
    async def generate_chat(
        self,
        messages: list[ChatTurn],
        *,
        system: str | None = None,
        max_tokens: int,
    ) -> ChatCompletion:
        """Return a completion for a role-based multi-turn conversation."""

    @abstractmethod
    async def embed(
        self,
        text: str,
        *,
        task_type: str | None = None,
        output_dimensionality: int | None = None,
    ) -> list[float]:
        """Return the embedding vector for ``text``."""
