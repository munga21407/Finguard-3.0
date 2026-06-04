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

from src.core.logging import logger
from src.core.metrics import HUB_WRITE_ERRORS
from src.domains.intelligence.schemas import InsightArtifact, OrchestratorState
from src.infrastructure.database.mongodb import get_mongo_db

COLLECTION = "intelligence_hub"

# Per-agent TTL mappings (Sprint 3-5 confirmed values)
_AGENT_TTL_HOURS: dict[str, int] = {
    "A": 1,    # Invoice Generator
    "B": 1,    # Transaction Classifier
    "C": 0,    # Reconciler — 10 min (see _AGENT_TTL_MINUTES)
    "D": 1,    # Cash-Flow Forecaster
    "E": 0,    # Budget Watchdog — 30 min (see _AGENT_TTL_MINUTES)
    "F": 24,   # Tax Auditor
    "G": 24,   # Credit Strategist
    "H": 1,    # Financial Advisor
    "I": 1,    # External Integrator — FX / credit / KRA data stale after 1 h
    "J": 0,    # Executive Summarizer — 30 min (see _AGENT_TTL_MINUTES)
}
_AGENT_TTL_MINUTES: dict[str, int] = {
    "C": 10,   # Reconciler
    "E": 30,   # Budget Watchdog
    "J": 30,   # Executive Summarizer
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

    Priority order reflects downstream dependency: most-recently-written
    agent keys are checked first so the correct artifact is written when
    hub_writer is called immediately after a specific agent.
    """
    # J — Executive Summarizer (final step, always last)
    if "executive_summary" in context:
        summary = context["executive_summary"]
        payload: dict[str, Any] = (
            {"summary": summary} if isinstance(summary, str) else summary
        )
        return ("J", "EXECUTIVE_SUMMARY", payload)

    # H — Financial Advisor
    if "advice" in context:
        return ("H", "ADVISORY_REQUEST", context["advice"])

    # G — Credit Strategist (include PDF/Excel exports when present)
    if "credit_strategy_result" in context:
        g_payload = dict(context["credit_strategy_result"])
        if "credit_report_pdf_b64" in context:
            g_payload["pdf_export_b64"] = context["credit_report_pdf_b64"]
        if "credit_forecast_xlsx_b64" in context:
            g_payload["xlsx_export_b64"] = context["credit_forecast_xlsx_b64"]
        return ("G", "REPORT_GENERATION", g_payload)

    # F — Tax Auditor
    if "audit_result" in context:
        return ("F", "AUDIT_REQUEST", context["audit_result"])

    # D — Cash-Flow Forecaster
    if "forecast" in context:
        fc = context["forecast"]
        return ("D", "CASH_FLOW_FORECAST", fc if isinstance(fc, dict) else {"data": fc})

    # E — Budget Watchdog
    if "watchdog_analysis" in context:
        return ("E", "BUDGET_WATCHDOG", context["watchdog_analysis"])

    # C — Reconciler
    if "reconciliation_report" in context:
        rr = context["reconciliation_report"]
        return (
            "C",
            "RECONCILIATION",
            rr if isinstance(rr, dict) else {"report": str(rr)},
        )

    # I — External Integrator
    if "external_data" in context:
        return ("I", "EXTERNAL_SYNC", context["external_data"])

    # A — Invoice Generator
    if "extracted_invoice" in context:
        return ("A", "GENERATE_INVOICE", context["extracted_invoice"])

    # B — Transaction Classifier
    if "classified_transactions" in context:
        return ("B", "CLASSIFY_TRANSACTIONS", context["classified_transactions"])

    return None


def make_hub_writer_node() -> Any:
    async def hub_writer_node(state: OrchestratorState) -> dict[str, Any]:
        result = _extract_payload_and_intent(state["context"])
        if result is None:
            logger.warning(
                "hub_writer: no recognizable agent key in context — "
                "passing state through unmodified",
                session_id=state.get("session_id"),
            )
            # Return the current context explicitly so downstream nodes are
            # never handed a wiped state from an empty-dict return.
            return {"context": state["context"]}

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
        try:
            await db[COLLECTION].replace_one({"_id": doc["_id"]}, doc, upsert=True)
        except Exception as exc:
            HUB_WRITE_ERRORS.inc()
            logger.error(
                "hub_writer: MongoDB upsert failed — artifact NOT persisted",
                artifact_id=doc["_id"],
                agent_id=agent_id,
                intent=intent,
                session_id=state.get("session_id"),
                error=str(exc),
                exc_info=True,
            )
            # Return the current context unmodified so the LangGraph run can
            # finish; hub_artifact_id is intentionally omitted to signal the
            # artifact was not written.
            return {"context": state["context"]}

        updated_context = dict(state["context"])
        updated_context["hub_artifact_id"] = doc["_id"]
        return {"context": updated_context}

    return hub_writer_node
