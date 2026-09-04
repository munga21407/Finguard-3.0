"""Unit tests for ``llm_client._build_client``'s provider-selection branching.

This is the one place that decides which vendor actually serves generative
calls (Fireworks vs. Gemini) and which one serves embeddings — untested until
now, which is how the embedding-routing bug (embeddings always hit `primary`,
crashing whenever Gemini was primary) shipped unnoticed. See
``test_llm_provider.py``'s embedding-routing tests for the ``FailoverLLMClient``
side of the same fix; these tests cover the wiring in ``_build_client`` itself.
"""
from __future__ import annotations

import pytest

from src.core.config import settings
from src.domains.intelligence import llm_client
from src.domains.intelligence.llm.failover import FailoverLLMClient
from src.domains.intelligence.llm.provider import OpenAICompatLLMClient


@pytest.fixture(autouse=True)
def _reset_provider_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every test starts from a clean slate — no provider keys set."""
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "")
    monkeypatch.setattr(settings, "FIREWORKS_API_KEY", "fw_test_key")
    monkeypatch.setattr(settings, "FEATHERLESS_API_KEY", "")
    monkeypatch.setattr(settings, "LLM_MODEL", "test/fireworks-model")
    monkeypatch.setattr(settings, "GEMINI_MODEL", "test/gemini-model")
    monkeypatch.setattr(settings, "EMBEDDING_MODEL", "test/embed-model")


def test_fireworks_is_primary_by_default() -> None:
    client = llm_client._build_client()
    assert isinstance(client, FailoverLLMClient)
    assert isinstance(client._primary, OpenAICompatLLMClient)
    assert client._primary.spec.name == "fireworks"
    assert client._primary.spec.model == "test/fireworks-model"
    assert client._primary.spec.embedding_model == "test/embed-model"


def test_fireworks_primary_serves_its_own_embeddings() -> None:
    """No GEMINI_API_KEY set: embedding_client should just be the primary —
    no redundant second client is constructed."""
    client = llm_client._build_client()
    assert client._embedding_client is client._primary


def test_gemini_becomes_primary_when_key_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "g_test_key")
    client = llm_client._build_client()
    assert client._primary.spec.name == "gemini"
    assert client._primary.spec.model == "test/gemini-model"
    assert client._primary.spec.embedding_model is None


def test_gemini_primary_still_routes_embeddings_to_fireworks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The bug this guards: embeddings must never go to Gemini, regardless of
    which provider is primary."""
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "g_test_key")
    client = llm_client._build_client()
    assert client._embedding_client is not client._primary
    assert client._embedding_client.spec.name == "fireworks"
    assert client._embedding_client.spec.embedding_model == "test/embed-model"


def test_featherless_backup_attached_only_when_key_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = llm_client._build_client()
    assert client._backup is None

    monkeypatch.setattr(settings, "FEATHERLESS_API_KEY", "rc_test_key")
    client = llm_client._build_client()
    assert isinstance(client._backup, OpenAICompatLLMClient)
    assert client._backup.spec.name == "featherless"


def test_featherless_backup_attached_regardless_of_which_primary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "g_test_key")
    monkeypatch.setattr(settings, "FEATHERLESS_API_KEY", "rc_test_key")
    client = llm_client._build_client()
    assert client._primary.spec.name == "gemini"
    assert client._backup is not None
    assert client._backup.spec.name == "featherless"


def test_active_model_id_mirrors_build_client_primary_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`active_model_id()` (used by security.agent_cards for signed VCs) must
    resolve to the same model `_build_client` actually wires up as primary —
    the two conditions are hand-duplicated (`if settings.GEMINI_API_KEY`), so
    this test is the tripwire if they ever drift apart."""
    assert llm_client.active_model_id() == "test/fireworks-model"
    assert llm_client._build_client()._primary.spec.model == "test/fireworks-model"

    monkeypatch.setattr(settings, "GEMINI_API_KEY", "g_test_key")
    assert llm_client.active_model_id() == "test/gemini-model"
    assert llm_client._build_client()._primary.spec.model == "test/gemini-model"
