"""Unit tests for the OpenAI-compatible provider + failover client with the
underlying ``openai`` transport mocked.

These verify the provider-agnostic interface plumbing — temperature passthrough,
structured-output request shaping, multimodal message assembly, embedding
extraction, timeout → LLMUnavailableError mapping — and the failover client's
primary→backup routing, all without any network or API key.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import BaseModel

from src.domains.intelligence.llm.base import BaseLLMClient, ChatTurn
from src.domains.intelligence.llm.failover import FailoverLLMClient
from src.domains.intelligence.llm.openai_compat import ProviderSpec
from src.domains.intelligence.llm.provider import LLMUnavailableError, OpenAICompatLLMClient

_SPEC = ProviderSpec(
    name="fireworks",
    api_key="x",
    base_url="http://local.test",
    model="test-model",
    structured_mode="json_schema",
    embedding_model="test-embed",
    embedding_dimensions=768,
)


class _Out(BaseModel):
    answer: str


class _FakeChatCompletions:
    def __init__(self, text: str, *, boom: bool, usage: Any) -> None:
        self._text = text
        self._boom = boom
        self._usage = usage
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if self._boom:
            raise TimeoutError("simulated hang")
        message = SimpleNamespace(content=self._text)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=self._usage)


class _FakeEmbeddings:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        # Unit-norm fixture so the provider's L2-normalization is a no-op and the
        # test asserts vector *extraction*, not the normalization arithmetic.
        return SimpleNamespace(data=[SimpleNamespace(embedding=[0.6, 0.8, 0.0])])


def _client(
    text: str = '{"answer":"hi"}', *, boom: bool = False, usage: Any = None
) -> tuple[OpenAICompatLLMClient, _FakeChatCompletions, _FakeEmbeddings]:
    chat_completions = _FakeChatCompletions(text, boom=boom, usage=usage)
    embeddings = _FakeEmbeddings()
    c = OpenAICompatLLMClient(_SPEC)
    # Inject the fake transport into the SDK wrapper the provider delegates to.
    c._sdk._client = SimpleNamespace(  # type: ignore[assignment]
        chat=SimpleNamespace(completions=chat_completions), embeddings=embeddings
    )
    return c, chat_completions, embeddings


@pytest.mark.asyncio
async def test_structured_validates_and_passes_temperature() -> None:
    c, chat, _ = _client('{"answer":"hi"}')
    out = await c.generate_structured("p", _Out, temperature=0.0)
    assert out.answer == "hi"
    assert chat.calls[0]["temperature"] == 0.0
    assert chat.calls[0]["response_format"]["type"] == "json_schema"


@pytest.mark.asyncio
async def test_structured_omits_temperature_when_none() -> None:
    c, chat, _ = _client('{"answer":"x"}')
    await c.generate_structured("p", _Out)
    assert "temperature" not in chat.calls[0]


@pytest.mark.asyncio
async def test_text_returns_response_text() -> None:
    c, _, _ = _client("plain answer")
    assert await c.generate_text("p", temperature=0.2) == "plain answer"


@pytest.mark.asyncio
async def test_vision_assembles_two_parts_and_validates() -> None:
    c, chat, _ = _client('{"answer":"ocr"}')
    out = await c.generate_vision_structured(
        "describe", image_bytes=b"img", mime_type="image/png", response_schema=_Out
    )
    assert out.answer == "ocr"
    content = chat.calls[0]["messages"][0]["content"]
    assert len(content) == 2  # text part + image_url part
    assert {p["type"] for p in content} == {"text", "image_url"}


@pytest.mark.asyncio
async def test_vision_text_returns_plain_text() -> None:
    c, chat, _ = _client("raw ocr text")
    out = await c.generate_vision_text("read", image_bytes=b"img", mime_type="image/png")
    assert out == "raw ocr text"
    assert len(chat.calls[0]["messages"][0]["content"]) == 2


@pytest.mark.asyncio
async def test_chat_maps_turns_and_returns_completion() -> None:
    usage = SimpleNamespace(prompt_tokens=5, completion_tokens=7)
    c, chat, _ = _client("hello there", usage=usage)
    out = await c.generate_chat(
        [ChatTurn(role="user", content="hi")], system="be brief", max_tokens=128
    )
    assert out.content == "hello there"
    assert out.input_tokens == 5 and out.output_tokens == 7
    messages = chat.calls[0]["messages"]
    assert messages[0] == {"role": "system", "content": "be brief"}
    assert messages[1] == {"role": "user", "content": "hi"}
    assert chat.calls[0]["max_tokens"] == 128


@pytest.mark.asyncio
async def test_chat_maps_model_role_to_assistant() -> None:
    c, chat, _ = _client("ok")
    await c.generate_chat([ChatTurn(role="model", content="prior")], max_tokens=32)
    assert chat.calls[0]["messages"][0]["role"] == "assistant"


@pytest.mark.asyncio
async def test_embed_returns_vector_and_passes_dimensions() -> None:
    c, _, embeddings = _client()
    vec = await c.embed("query", task_type="RETRIEVAL_QUERY", output_dimensionality=3)
    assert vec == [0.6, 0.8, 0.0]
    assert embeddings.calls[0]["dimensions"] == 3
    assert embeddings.calls[0]["input"].startswith("search_query: ")


@pytest.mark.asyncio
async def test_timeout_maps_to_llm_unavailable() -> None:
    c, _, _ = _client(boom=True)
    with pytest.raises(LLMUnavailableError):
        await c.generate_structured("p", _Out)


# ---------------------------------------------------------------------------
# Failover client
# ---------------------------------------------------------------------------


class _StubClient(BaseLLMClient):
    """Minimal BaseLLMClient that returns a fixed answer or raises."""

    def __init__(self, answer: str | None, *, fail: bool = False) -> None:
        self._answer = answer
        self._fail = fail
        self.text_calls = 0

    async def generate_text(self, prompt: str, *, temperature: float | None = None) -> str:
        self.text_calls += 1
        if self._fail:
            raise LLMUnavailableError("stub down")
        assert self._answer is not None
        return self._answer

    async def generate_structured(self, prompt, response_schema, *, temperature=None):  # type: ignore[no-untyped-def]
        raise NotImplementedError

    async def generate_vision_structured(self, prompt, *, image_bytes, mime_type, response_schema, temperature=None, model=None):  # type: ignore[no-untyped-def]
        raise NotImplementedError

    async def generate_vision_text(self, prompt, *, image_bytes, mime_type, temperature=None, model=None):  # type: ignore[no-untyped-def]
        raise NotImplementedError

    async def generate_chat(self, messages, *, system=None, max_tokens):  # type: ignore[no-untyped-def]
        raise NotImplementedError

    async def embed(self, text, *, task_type=None, output_dimensionality=None):  # type: ignore[no-untyped-def]
        raise NotImplementedError


@pytest.mark.asyncio
async def test_failover_uses_primary_when_healthy() -> None:
    primary, backup = _StubClient("primary"), _StubClient("backup")
    fo = FailoverLLMClient(primary, backup)
    assert await fo.generate_text("p") == "primary"
    assert backup.text_calls == 0


@pytest.mark.asyncio
async def test_failover_routes_to_backup_on_primary_failure() -> None:
    primary, backup = _StubClient(None, fail=True), _StubClient("backup")
    fo = FailoverLLMClient(primary, backup)
    assert await fo.generate_text("p") == "backup"
    assert primary.text_calls == 1 and backup.text_calls == 1


@pytest.mark.asyncio
async def test_failover_raises_when_both_fail() -> None:
    fo = FailoverLLMClient(_StubClient(None, fail=True), _StubClient(None, fail=True))
    with pytest.raises(LLMUnavailableError):
        await fo.generate_text("p")


@pytest.mark.asyncio
async def test_failover_without_backup_propagates() -> None:
    fo = FailoverLLMClient(_StubClient(None, fail=True), None)
    with pytest.raises(LLMUnavailableError):
        await fo.generate_text("p")
