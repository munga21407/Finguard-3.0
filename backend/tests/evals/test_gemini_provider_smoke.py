"""Live smoke test for the Gemini alternative primary provider.

`OpenAICompatLLMClient`'s ``extra_body`` for Gemini is deliberately left empty
(see ``llm/openai_compat.py``'s module docstring) because — unlike Fireworks
and Featherless, which the docstring says were "all verified live" — nobody
had actually exercised a real call against Gemini. This test closes that gap:
one real structured call and one real chat call, run directly against the
Gemini ``ProviderSpec`` (not through the failover/primary-selection machinery,
so it tests the Gemini wiring specifically regardless of which provider a
given environment has configured as primary).

Opt-in only, like the other `tests/evals` LLM-judge tests:
  * costs tokens and needs a real `GEMINI_API_KEY`;
  * network-dependent, so it must never gate a PR — nightly only (see the
    `llm-evals` job in `.github/workflows/ci.yml`, which already sets
    `GEMINI_API_KEY` for this suite).

If this starts failing (empty/truncated replies), Gemini likely needs the same
thinking-mode-off treatment Gemma gets on Fireworks/Featherless — extend
`GEMINI_EXTRA_BODY` in `openai_compat.py` and give `_build_client`'s Gemini
`ProviderSpec` a non-empty `extra_body`.
"""
from __future__ import annotations

import os

import pytest
from pydantic import BaseModel

from src.core.config import settings
from src.domains.intelligence.llm.base import ChatTurn
from src.domains.intelligence.llm.openai_compat import ProviderSpec
from src.domains.intelligence.llm.provider import OpenAICompatLLMClient

pytestmark = [
    pytest.mark.llm_judge,
    pytest.mark.skipif(
        not (os.getenv("RUN_LLM_EVALS") and settings.GEMINI_API_KEY),
        reason=(
            "Gemini smoke test is nightly/opt-in — set RUN_LLM_EVALS=1 and "
            "GEMINI_API_KEY"
        ),
    ),
]


def _gemini_client() -> OpenAICompatLLMClient:
    return OpenAICompatLLMClient(
        ProviderSpec(
            name="gemini",
            api_key=settings.GEMINI_API_KEY,
            base_url=settings.GEMINI_API_BASE,
            model=settings.GEMINI_MODEL,
            structured_mode="json_schema",
            embedding_model=None,
            extra_body={},
        )
    )


class _Greeting(BaseModel):
    language: str
    greeting: str


@pytest.mark.asyncio
async def test_gemini_structured_output_returns_valid_schema() -> None:
    client = _gemini_client()
    out = await client.generate_structured(
        "Return a greeting in French.", _Greeting, temperature=0.0
    )
    assert out.language
    assert out.greeting


@pytest.mark.asyncio
async def test_gemini_chat_returns_nonempty_content() -> None:
    """Guards against the exact failure mode Gemma needs thinking-mode-off
    for: a reply silently swallowed into hidden reasoning, returning empty
    content instead of the answer."""
    client = _gemini_client()
    completion = await client.generate_chat(
        [ChatTurn(role="user", content="Reply with exactly the word: pong")],
        max_tokens=64,
    )
    assert completion.content.strip()
