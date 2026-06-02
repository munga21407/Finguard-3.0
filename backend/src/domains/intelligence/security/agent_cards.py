"""
Agent identity cards — static metadata profiles for each AI agent.

Used by the VC issuer and audit log to record which agent performed
an operation, what model version it ran, and what capabilities it
exercised. Cards are immutable at runtime.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AgentCard:
    agent_id: str
    name: str
    version: str
    capabilities: tuple[str, ...]
    model: str = "gemini-2.5-flash"
    issuer: str = "finguard-system"


AGENT_CARDS: dict[str, AgentCard] = {
    "A": AgentCard(
        agent_id="A",
        name="Invoice Generator",
        version="v1.0",
        capabilities=("invoice_extraction", "structured_output"),
    ),
    "B": AgentCard(
        agent_id="B",
        name="Receipt Scanner",
        version="v1.0",
        capabilities=("receipt_ocr", "transaction_classification"),
    ),
    "C": AgentCard(
        agent_id="C",
        name="Reconciliation Engine",
        version="v1.0",
        capabilities=("exact_match", "fuzzy_match", "llm_fallback"),
    ),
    "D": AgentCard(
        agent_id="D",
        name="Cash-Flow Forecaster",
        version="v1.0",
        capabilities=("time_series_forecast", "ledger_analysis"),
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
    ),
    "F": AgentCard(
        agent_id="F",
        name="Compliance Auditor",
        version="v1.0",
        capabilities=("rule_based_audit", "aml_screening", "duplicate_detection"),
    ),
    "G": AgentCard(
        agent_id="G",
        name="Report Generator",
        version="v1.0",
        capabilities=("pdf_generation", "excel_export", "narrative_summary"),
    ),
    "H": AgentCard(
        agent_id="H",
        name="Financial Advisor",
        version="v1.0",
        capabilities=("personalised_advice", "risk_assessment"),
    ),
    "I": AgentCard(
        agent_id="I",
        name="External Integrator",
        version="v1.0",
        capabilities=("mpesa_api", "fx_rates", "kyc_lookup"),
    ),
    "J": AgentCard(
        agent_id="J",
        name="Executive Summarizer",
        version="v1.0",
        capabilities=("executive_summary", "locale_translation"),
    ),
}


def get_card(agent_id: str) -> AgentCard:
    """Return the card for a given agent ID, raising KeyError if unknown."""
    return AGENT_CARDS[agent_id]
