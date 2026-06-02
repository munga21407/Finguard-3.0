"""
Hub Writer node — MongoDB intelligence_hub upsert.

Reads the agent output from `state["context"]`, wraps it in an
InsightArtifact, and upserts it into the `intelligence_hub` collection.
The document key is `"<agent_id>:<intent>"` so repeated invocations
refresh the cached artifact rather than creating duplicates.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from src.domains.intelligence.schemas import InsightArtifact, OrchestratorState
from src.infrastructure.database.mongodb import get_mongo_db

COLLECTION = "intelligence_hub"

# Per-agent TTL in hours (from SYSTEM_OVERVIEW.md)
_AGENT_TTL_HOURS: dict[str, int] = {
    "A": 1,    # Invoice Generator
    "B": 1,    # Receipt Scanner
    "C": 0,    # Reconciliation — 15 min → stored as float below
    "D": 1,    # Financial Analyst
    "E": 0,    # Budget Watchdog — 30 min
    "F": 24,   # Tax Auditor
    "G": 24,   # Credit Strategist
    "H": 0,    # Fraud Sentinel — 5 min
    "I": 1,    # Dunning Profiler
    "J": 1,    # Stockout Oracle
}
_AGENT_TTL_MINUTES: dict[str, int] = {
    "C": 15,
    "E": 30,
    "H": 5,
}


def _ttl_delta(agent_id: str) -> timedelta:
    if agent_id in _AGENT_TTL_MINUTES:
        return timedelta(minutes=_AGENT_TTL_MINUTES[agent_id])
    hours = _AGENT_TTL_HOURS.get(agent_id, 1)
    return timedelta(hours=hours)


def _extract_payload_and_intent(context: dict[str, Any]) -> tuple[str, str, dict[str, Any]] | None:
    """
    Inspect the context dict and return (agent_id, intent, payload).
    Returns None if no recognisable agent output is found.

    Priority order ensures the most recently written agent result is picked up
    when multiple agents have run within the same state.  The Celery reporting
    task clears earlier keys before invoking each subsequent hub write so each
    call lands on the correct agent slot.
    """
    if "credit_strategy_result" in context:
        return ("G", "REPORT_GENERATION", context["credit_strategy_result"])
    if "audit_result" in context:
        return ("F", "AUDIT_REQUEST", context["audit_result"])
    if "extracted_invoice" in context:
        return ("A", "GENERATE_INVOICE", context["extracted_invoice"])
    if "watchdog_analysis" in context:
        return ("E", "BUDGET_WATCHDOG", context["watchdog_analysis"])
    if "classified_transactions" in context:
        return ("B", "SCAN_RECEIPT", context["classified_transactions"])
    return None


def make_hub_writer_node():
    async def hub_writer_node(state: OrchestratorState) -> dict:
        result = _extract_payload_and_intent(state["context"])
        if result is None:
            # Nothing to cache — pass through silently
            return {}

        agent_id, intent, payload = result
        now = datetime.now(UTC)

        artifact = InsightArtifact(
            agent_id=agent_id,
            intent=intent,
            payload=payload,
            ttl_expires_at=now + _ttl_delta(agent_id),
            created_at=now,
        )

        doc: dict[str, Any] = artifact.model_dump()
        doc["_id"] = f"{agent_id}:{intent}"          # idempotent compound key
        doc["ttl_expires_at"] = doc["ttl_expires_at"].isoformat()
        doc["created_at"] = doc["created_at"].isoformat()

        db = get_mongo_db()
        await db[COLLECTION].replace_one({"_id": doc["_id"]}, doc, upsert=True)

        updated_context = dict(state["context"])
        updated_context["hub_artifact_id"] = doc["_id"]
        return {"context": updated_context}

    return hub_writer_node
