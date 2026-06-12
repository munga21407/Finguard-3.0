"""
Hub Writer node — MongoDB intelligence_hub upsert.

Reads the agent output from `state["context"]`, wraps it in an
InsightArtifact, and upserts it into the `intelligence_hub` collection.
The document key is `"<agent_id>:<intent>"` so repeated invocations
refresh the cached artifact rather than creating duplicates.

GenUI payloads from `state["gen_ui_payloads"]` are persisted separately
under the key `"genui:<session_id>:<component_id>"` with a 1-hour TTL.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from src.core.logging import logger
from src.core.metrics import HUB_WRITE_ERRORS
from src.domains.intelligence.schemas import (
    GenUIArtifact,
    GenUIPayload,
    InsightArtifact,
    OrchestratorState,
)
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

# GenUI payloads are session-scoped UI state; 1 h matches the shortest agent TTL
_GENUI_TTL_HOURS = 1


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


async def _persist_gen_ui_payloads(
    db: Any,
    payloads: list[GenUIPayload],
    session_id: str,
    now: datetime,
) -> list[str]:
    """
    Upsert each GenUIPayload into `intelligence_hub` and return the written IDs.

    Document key: ``"genui:<session_id>:<component_id>"``
    Repeated renders of the same component within a session refresh the
    document rather than creating duplicates; props always reflect the
    latest invocation.
    """
    artifact_ids: list[str] = []
    ttl_expires_at = now + timedelta(hours=_GENUI_TTL_HOURS)

    for payload in payloads:
        artifact = GenUIArtifact(
            component_id=payload.component_id,
            props=payload.props,
            fallback_text=payload.fallback_text,
            session_id=session_id,
            ttl_expires_at=ttl_expires_at,
            created_at=now,
        )
        doc: dict[str, Any] = artifact.model_dump()
        doc["_id"] = f"genui:{session_id}:{payload.component_id}"
        doc["type"] = "gen_ui"
        doc["ttl_expires_at"] = doc["ttl_expires_at"].isoformat()
        doc["created_at"] = doc["created_at"].isoformat()

        try:
            await db[COLLECTION].replace_one({"_id": doc["_id"]}, doc, upsert=True)
            artifact_ids.append(doc["_id"])
        except Exception as exc:
            HUB_WRITE_ERRORS.inc()
            logger.error(
                "hub_writer: GenUI payload upsert failed — artifact NOT persisted",
                artifact_id=doc["_id"],
                component_id=payload.component_id,
                session_id=session_id,
                error=str(exc),
                exc_info=True,
            )

    return artifact_ids


def make_hub_writer_node() -> Any:
    async def hub_writer_node(state: OrchestratorState) -> dict[str, Any]:
        now = datetime.now(UTC)
        db = get_mongo_db()
        session_id: str = state.get("session_id", "")
        updated_context = dict(state["context"])

        # --- GenUI payloads ------------------------------------------------
        gen_ui_payloads: list[GenUIPayload] = state.get("gen_ui_payloads") or []
        if gen_ui_payloads:
            written_ids = await _persist_gen_ui_payloads(db, gen_ui_payloads, session_id, now)
            if written_ids:
                updated_context["hub_genui_artifact_ids"] = written_ids
                logger.info(
                    "hub_writer: persisted GenUI payloads",
                    count=len(written_ids),
                    artifact_ids=written_ids,
                    session_id=session_id,
                )

        # --- Agent insight artifacts ----------------------------------------
        result = _extract_payload_and_intent(state["context"])
        if result is None:
            if not gen_ui_payloads:
                logger.warning(
                    "hub_writer: no recognizable agent key in context and no "
                    "GenUI payloads — passing state through unmodified",
                    session_id=session_id,
                )
            return {"context": updated_context}

        agent_id, intent, payload = result

        artifact = InsightArtifact(
            agent_id=agent_id,
            intent=intent,
            payload=payload,
            ttl_expires_at=now + _ttl_delta(agent_id),
            created_at=now,
        )

        doc: dict[str, Any] = artifact.model_dump()
        doc["_id"] = f"{agent_id}:{intent}"          # idempotent compound key
        doc["type"] = "insight"
        doc["ttl_expires_at"] = doc["ttl_expires_at"].isoformat()
        doc["created_at"] = doc["created_at"].isoformat()

        try:
            await db[COLLECTION].replace_one({"_id": doc["_id"]}, doc, upsert=True)
        except Exception as exc:
            HUB_WRITE_ERRORS.inc()
            logger.error(
                "hub_writer: MongoDB upsert failed — artifact NOT persisted",
                artifact_id=doc["_id"],
                agent_id=agent_id,
                intent=intent,
                session_id=session_id,
                error=str(exc),
                exc_info=True,
            )
            # Return whatever context we've accumulated (may include GenUI IDs)
            return {"context": updated_context}

        updated_context["hub_artifact_id"] = doc["_id"]
        return {"context": updated_context}

    return hub_writer_node
