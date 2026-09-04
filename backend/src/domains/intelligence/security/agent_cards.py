"""
Agent identity cards — static metadata profiles for each AI agent (Sprint 6).

Sprint 6 additions
-------------------
- **Decentralized Identifiers (DIDs):** every agent now carries a W3C DID
  of the form ``did:web:finguard.internal:agent:<slug>``.
- **Ed25519 card signatures:** each card is signed by the internal CA
  (key_manager.py) before being handed to any caller. The signature covers
  a deterministic canonical JSON serialisation of the card's core fields.
- **Zero-trust exchange:** ``exchange_cards(sender, receiver)`` verifies
  both cards' CA signatures before allowing state to pass between agents.
  **Not currently called anywhere** — the planner's actual inter-agent
  handoff is in-process (LangGraph's ``Send``, dispatched by
  ``agents/planner.py``), not a call across a trust boundary this would
  guard. It's the right primitive for a *genuine* agent-to-agent exchange —
  e.g. if agent execution ever moves to a separate service from write
  execution — not for today's single-process orchestration. Exercised only
  by unit tests until that boundary exists.

Cards are signed lazily on first access and cached for the process lifetime.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from src.core.logging import logger
from src.domains.intelligence.llm_client import active_model_id
from src.domains.intelligence.security.key_manager import sign_data, verify_signature


@dataclass(frozen=True)
class AgentCard:
    agent_id: str
    name: str
    version: str
    capabilities: tuple[str, ...]
    did: str                                   # W3C DID (did:web:…)
    # Resolved from live config at construction time (mirrors
    # llm_client._build_client's own primary-selection condition) so a signed
    # card can never claim a model other than the one actually configured —
    # not a hardcoded literal, which would silently go stale the moment
    # LLM_MODEL or GEMINI_API_KEY changes.
    model: str = field(default_factory=active_model_id)
    issuer: str = "finguard-system"
    card_signature: bytes = field(           # Ed25519 sig over canonical JSON
        default=b"",
        compare=False,
        hash=False,
    )


# ---------------------------------------------------------------------------
# Canonical serialisation (signature covers these fields — order is stable)
# ---------------------------------------------------------------------------

def _card_canonical(card: AgentCard) -> bytes:
    """Deterministic JSON bytes of a card's core fields (excluding signature)."""
    doc: dict[str, Any] = {
        "agent_id": card.agent_id,
        "capabilities": sorted(card.capabilities),
        "did": card.did,
        "issuer": card.issuer,
        "model": card.model,
        "name": card.name,
        "version": card.version,
    }
    return json.dumps(doc, sort_keys=True, separators=(",", ":")).encode()


# ---------------------------------------------------------------------------
# CA signing and verification
# ---------------------------------------------------------------------------

def sign_card(card: AgentCard) -> AgentCard:
    """Return a new AgentCard with a fresh CA signature embedded."""
    sig = sign_data(_card_canonical(card))
    return AgentCard(
        agent_id=card.agent_id,
        name=card.name,
        version=card.version,
        capabilities=card.capabilities,
        did=card.did,
        model=card.model,
        issuer=card.issuer,
        card_signature=sig,
    )


def verify_card(card: AgentCard) -> bool:
    """
    Return True if the card carries a valid CA signature.

    A card with no signature (card_signature == b"") always returns False.
    """
    if not card.card_signature:
        return False
    return verify_signature(_card_canonical(card), card.card_signature)


def exchange_cards(sender: AgentCard, receiver: AgentCard) -> None:
    """
    Zero-trust pre-flight identity check between two agents.

    Both cards must carry a valid CA signature before state is allowed to pass.
    Not currently called by any live handoff — see the module docstring.

    Raises:
        PermissionError: if either card fails signature verification.
    """
    if not verify_card(sender):
        raise PermissionError(
            f"Agent card verification failed for sender: {sender.did} "
            f"(agent_id={sender.agent_id!r})"
        )
    if not verify_card(receiver):
        raise PermissionError(
            f"Agent card verification failed for receiver: {receiver.did} "
            f"(agent_id={receiver.agent_id!r})"
        )
    logger.debug(
        "Agent card exchange verified",
        sender_did=sender.did,
        receiver_did=receiver.did,
    )


# ---------------------------------------------------------------------------
# Card registry — signed lazily on first get_card() call
# ---------------------------------------------------------------------------

_UNSIGNED_CARDS: dict[str, AgentCard] = {
    "A": AgentCard(
        agent_id="A",
        name="Invoice Generator",
        version="v1.0",
        capabilities=("invoice_extraction", "structured_output"),
        did="did:web:finguard.internal:agent:a_generator",
    ),
    "B": AgentCard(
        agent_id="B",
        name="Receipt Scanner",
        version="v1.0",
        capabilities=("receipt_ocr", "transaction_classification"),
        did="did:web:finguard.internal:agent:b_classifier",
    ),
    "C": AgentCard(
        agent_id="C",
        name="Reconciliation Engine",
        version="v1.0",
        capabilities=("exact_match", "fuzzy_match", "llm_fallback"),
        did="did:web:finguard.internal:agent:c_reconciler",
    ),
    "D": AgentCard(
        agent_id="D",
        name="Cash-Flow Forecaster",
        version="v1.0",
        capabilities=("time_series_forecast", "ledger_analysis"),
        did="did:web:finguard.internal:agent:d_forecaster",
    ),
    "E": AgentCard(
        agent_id="E",
        name="Budget Watchdog",
        version="v4.2",
        capabilities=(
            "hmm_state_detection",
            "forward_algorithm",
            "isolation_forest",
            "duplicate_detection",
            "vc_issuance",
            "rabbitmq_consumer",
        ),
        did="did:web:finguard.internal:agent:e_watchdog",
    ),
    "F": AgentCard(
        agent_id="F",
        name="Compliance Auditor",
        version="v1.0",
        capabilities=("rule_based_audit", "aml_screening", "duplicate_detection"),
        did="did:web:finguard.internal:agent:f_auditor",
    ),
    "G": AgentCard(
        agent_id="G",
        name="Report Generator",
        version="v1.0",
        capabilities=("pdf_generation", "excel_export", "narrative_summary"),
        did="did:web:finguard.internal:agent:g_reporter",
    ),
    "H": AgentCard(
        agent_id="H",
        name="Financial Advisor",
        version="v1.0",
        capabilities=("personalised_advice", "risk_assessment"),
        did="did:web:finguard.internal:agent:h_advisor",
    ),
    "I": AgentCard(
        agent_id="I",
        name="External Integrator",
        version="v1.0",
        capabilities=("mpesa_api", "fx_rates", "kyc_lookup"),
        did="did:web:finguard.internal:agent:i_integrator",
    ),
    "J": AgentCard(
        agent_id="J",
        name="Executive Summarizer",
        version="v1.0",
        capabilities=("executive_summary", "locale_translation"),
        did="did:web:finguard.internal:agent:j_summarizer",
    ),
    "K": AgentCard(
        agent_id="K",
        name="Stock Steward",
        version="v1.0",
        capabilities=("inventory_analysis", "stock_adjustment_proposal", "vc_issuance"),
        did="did:web:finguard.internal:agent:k_stockkeeper",
    ),
}

_SIGNED_CARDS: dict[str, AgentCard] = {}


def get_card(agent_id: str) -> AgentCard:
    """
    Return the CA-signed AgentCard for a given agent ID.

    Cards are signed lazily on first access so key material is only loaded
    after env vars are available (i.e. after application startup).

    Raises:
        KeyError: if agent_id is not in the registry.
    """
    if agent_id not in _SIGNED_CARDS:
        unsigned = _UNSIGNED_CARDS[agent_id]  # raises KeyError for unknown IDs
        _SIGNED_CARDS[agent_id] = sign_card(unsigned)
    return _SIGNED_CARDS[agent_id]
