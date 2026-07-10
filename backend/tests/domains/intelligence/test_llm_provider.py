"""Unit tests for the GeminiLLMClient capability surface (structured/text/vision/
embed) with the underlying google-genai client mocked.

These verify the provider-agnostic interface plumbing — temperature passthrough,
multimodal part assembly, embedding extraction, and timeout → LLMUnavailableError
mapping — without any network or API key.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import BaseModel

from src.domains.intelligence.llm.gemini import GeminiLLMClient, LLMUnavailableError


class _Out(BaseModel):
    answer: str


class _Resp:
    def __init__(self, text: str) -> None:
        self.text = text
        self.usage_metadata = None


class _FakeModels:
    def __init__(self, text: str, *, boom: bool = False) -> None:
        self._text = text
        self._boom = boom
        self.calls: list[dict[str, Any]] = []

    async def generate_content(self, **kwargs: Any) -> _Resp:
        self.calls.append(kwargs)
        if self._boom:
            raise TimeoutError("simulated hang")
        return _Resp(self._text)

    async def embed_content(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        # Unit-norm fixture so the provider's L2-normalization is a no-op and the
        # test asserts vector *extraction*, not the normalization arithmetic.
        return SimpleNamespace(embeddings=[SimpleNamespace(values=[0.6, 0.8, 0.0])])


def _client(text: str = '{"answer":"hi"}', *, boom: bool = False) -> tuple[GeminiLLMClient, _FakeModels]:
    models = _FakeModels(text, boom=boom)
    c = GeminiLLMClient()
    # Inject the fake transport into the SDK wrapper the provider delegates to.
    c._sdk._client = SimpleNamespace(aio=SimpleNamespace(models=models))  # type: ignore[assignment]
    return c, models


@pytest.mark.asyncio
async def test_structured_validates_and_passes_temperature() -> None:
    c, models = _client('{"answer":"hi"}')
    out = await c.generate_structured("p", _Out, temperature=0.0)
    assert out.answer == "hi"
    assert models.calls[0]["config"].temperature == 0.0


@pytest.mark.asyncio
async def test_structured_omits_temperature_when_none() -> None:
    c, models = _client('{"answer":"x"}')
    await c.generate_structured("p", _Out)
    assert models.calls[0]["config"].temperature is None


@pytest.mark.asyncio
async def test_text_returns_response_text() -> None:
    c, _ = _client("plain answer")
    assert await c.generate_text("p", temperature=0.2) == "plain answer"


@pytest.mark.asyncio
async def test_vision_assembles_two_parts_and_validates() -> None:
    c, models = _client('{"answer":"ocr"}')
    out = await c.generate_vision_structured(
        "describe", image_bytes=b"img", mime_type="image/png", response_schema=_Out
    )
    assert out.answer == "ocr"
    assert len(models.calls[0]["contents"]) == 2  # image part + text part


@pytest.mark.asyncio
async def test_vision_text_returns_plain_text() -> None:
    c, models = _client("raw ocr text")
    out = await c.generate_vision_text(
        "read", image_bytes=b"img", mime_type="image/png"
    )
    assert out == "raw ocr text"
    assert len(models.calls[0]["contents"]) == 2  # image part + text part


@pytest.mark.asyncio
async def test_chat_maps_turns_and_returns_completion() -> None:
    from src.domains.intelligence.llm.base import ChatTurn

    c, models = _client("hello there")
    out = await c.generate_chat(
        [ChatTurn(role="user", content="hi")], system="be brief", max_tokens=128
    )
    assert out.content == "hello there"
    assert out.input_tokens == 0 and out.output_tokens == 0  # usage_metadata None
    assert models.calls[0]["config"].system_instruction == "be brief"
    assert models.calls[0]["config"].max_output_tokens == 128


@pytest.mark.asyncio
async def test_embed_returns_vector() -> None:
    c, models = _client()
    vec = await c.embed("query", task_type="RETRIEVAL_QUERY", output_dimensionality=3)
    assert vec == [0.6, 0.8, 0.0]
    assert models.calls[0]["config"] is not None  # EmbedContentConfig built


@pytest.mark.asyncio
async def test_timeout_maps_to_llm_unavailable() -> None:
    c, _ = _client(boom=True)
    with pytest.raises(LLMUnavailableError):
        await c.generate_structured("p", _Out)
