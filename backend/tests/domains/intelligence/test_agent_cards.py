"""Signed AgentCard identity — the `model` field must track live config.

Before this fix, `AgentCard.model` was a hardcoded literal ("gemma-4-31b-it")
baked into every card, signed as-is by the internal CA and embedded in every
Verifiable Credential `issue_vc()` writes to `trust_log`. Changing `LLM_MODEL`,
or switching the primary provider to Gemini via `GEMINI_API_KEY`, made every
subsequently-signed card assert a false claim about which model actually ran —
a correctness gap in a security/audit artifact, not just documentation drift.
"""
from __future__ import annotations

import pytest

from src.core.config import settings
from src.domains.intelligence import llm_client
from src.domains.intelligence.security import agent_cards


@pytest.fixture(autouse=True)
def _reset_cached_cards(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cards are cached at module scope for the process lifetime (by design —
    see the module docstring); tests must not leak that cache between cases."""
    monkeypatch.setattr(agent_cards, "_SIGNED_CARDS", {})


def test_card_model_matches_active_model_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "")
    monkeypatch.setattr(settings, "LLM_MODEL", "accounts/x/deployments/y")
    card = agent_cards.AgentCard(
        agent_id="A", name="n", version="v1", capabilities=(), did="did:web:test:a"
    )
    assert card.model == "accounts/x/deployments/y"
    assert card.model == llm_client.active_model_id()


def test_card_model_switches_to_gemini_when_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "g_test_key")
    monkeypatch.setattr(settings, "GEMINI_MODEL", "gemini-test-model")
    card = agent_cards.AgentCard(
        agent_id="A", name="n", version="v1", capabilities=(), did="did:web:test:a"
    )
    assert card.model == "gemini-test-model"


def test_get_card_resolves_every_registered_letter() -> None:
    """A–K must all be present and signable — Agent K's card was previously
    missing entirely (KeyError from `get_card("K")`)."""
    for agent_id in "ABCDEFGHIJK":
        card = agent_cards.get_card(agent_id)
        assert card.agent_id == agent_id
        assert agent_cards.verify_card(card)


def test_get_card_unknown_id_raises_keyerror() -> None:
    with pytest.raises(KeyError):
        agent_cards.get_card("k_stockkeeper")


# ── verify_own_card (P2 of "Task-scoped VC end-to-end") ────────────────────────

def test_verify_own_card_passes_for_a_valid_registered_agent() -> None:
    agent_cards.verify_own_card("C")  # must not raise


def test_verify_own_card_raises_for_unknown_agent() -> None:
    with pytest.raises(KeyError):
        agent_cards.verify_own_card("not-a-real-agent")


def test_verify_own_card_raises_when_signature_invalid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(agent_cards, "verify_card", lambda card: False)
    with pytest.raises(PermissionError, match="card verification failed"):
        agent_cards.verify_own_card("C")
