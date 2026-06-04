"""
Celery Reporting Tasks — monthly AI intelligence report generation.

Celery workers are synchronous; the LangGraph agents are async.
Bridge strategy:
  - Each task calls `asyncio.run(_async_runner(...))` which spins up a
    fresh event loop, runs both async agents to completion, and tears
    it down — the standard, safe pattern for sync→async bridging.
  - SQLAlchemy's async engine uses asyncpg, which binds connections to
    the running event loop.  Because Celery workers are forked processes
    each with their own module-level import chain, the AsyncSessionLocal
    singleton is fresh per worker process and compatible with the
    loop created by asyncio.run().
  - Agent nodes are called directly (not via the compiled StateGraph) to
    avoid the overhead of the Gemini-based supervisor routing LLM call.
    hub_writer_node is invoked once per agent, with the previous agent's
    context key cleared first so the hub always writes the correct slot.

Task return shape:
    {
        "sme_id": str,
        "agent_f_artifact_id": str | None,   # MongoDB _id in intelligence_hub
        "agent_g_artifact_id": str | None,
        "status": "ok" | "partial" | "failed",
    }
"""
from __future__ import annotations

import asyncio
import uuid
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from src.domains.intelligence.agents.f_auditor import make_f_auditor_node
from src.domains.intelligence.agents.g_reporter import make_g_reporter_node
from src.domains.intelligence.agents.hub_writer import make_hub_writer_node
from src.infrastructure.database.mongodb import init_mongo
from src.infrastructure.database.postgres import AsyncSessionLocal
from src.workers.tasks.celery_app import celery_app

logger = structlog.get_logger(__name__)

# ── Data-fetch helpers ────────────────────────────────────────────────────────

async def _fetch_ledger_snapshot(sme_id: str) -> dict[str, Any]:
    """Aggregate 12-month totals for the audit context."""
    sql = text("""
        SELECT
            COALESCE(SUM(CASE WHEN transaction_type = 'credit'
                             THEN amount ELSE 0 END), 0) AS revenue,
            COALESCE(SUM(CASE WHEN transaction_type = 'debit'
                             THEN amount ELSE 0 END), 0) AS opex,
            COUNT(*)  AS tx_count,
            MAX(amount) AS max_single_tx
        FROM ledger_entries
        WHERE created_at >= NOW() - INTERVAL '365 days'
    """)
    async with AsyncSessionLocal() as session:
        try:
            result = await session.execute(sql)
            row = result.fetchone()
        except SQLAlchemyError as exc:
            logger.exception(
                "reporting: _fetch_ledger_snapshot DB query failed",
                sme_id=sme_id,
                error=str(exc),
                exc_info=True,
            )
            raise
    if row:
        return {
            "revenue":       float(row[0] or 0),
            "opex":          float(row[1] or 0),
            "tx_count":      int(row[2] or 0),
            "max_single_tx": float(row[3] or 0),
        }
    return {"revenue": 0.0, "opex": 0.0, "tx_count": 0, "max_single_tx": 0.0}


async def _fetch_monthly_cashflows(sme_id: str) -> dict[str, Any]:
    """Monthly revenue / opex buckets for the trailing 12 months (oldest-first)."""
    sql = text("""
        SELECT
            TO_CHAR(DATE_TRUNC('month', created_at), 'YYYY-MM') AS month,
            COALESCE(SUM(CASE WHEN transaction_type = 'credit'
                             THEN amount ELSE 0 END), 0) AS revenue,
            COALESCE(SUM(CASE WHEN transaction_type = 'debit'
                             THEN amount ELSE 0 END), 0) AS opex
        FROM ledger_entries
        WHERE created_at >= NOW() - INTERVAL '12 months'
        GROUP BY DATE_TRUNC('month', created_at)
        ORDER BY 1
    """)
    async with AsyncSessionLocal() as session:
        try:
            result = await session.execute(sql)
            rows = result.fetchall()
        except SQLAlchemyError as exc:
            logger.exception(
                "reporting: _fetch_monthly_cashflows DB query failed",
                sme_id=sme_id,
                error=str(exc),
                exc_info=True,
            )
            raise
    return {
        "months":           [r[0] for r in rows],
        "monthly_inflows":  [float(r[1] or 0) for r in rows],
        "monthly_outflows": [float(r[2] or 0) for r in rows],
    }


# ── Minimal state builder ─────────────────────────────────────────────────────

def _make_state(context: dict[str, Any]) -> dict[str, Any]:
    return {
        "messages": [],
        "next": "FINISH",
        "context": context,
        "session_id": str(uuid.uuid4()),
        "user_id": None,
        "mode": "actions",
    }


# ── Core async runner ─────────────────────────────────────────────────────────

async def _run_intelligence_report(sme_id: str) -> dict[str, Any]:
    """
    Async coroutine that runs Agent F then Agent G and writes both artifacts
    to MongoDB intelligence_hub via hub_writer_node.

    Returns the two MongoDB _id values so the UI can poll for them.
    """
    await init_mongo()

    # Pre-load ledger data once; share across both agents
    ledger_snapshot = await _fetch_ledger_snapshot(sme_id)
    raw_ledger_data = await _fetch_monthly_cashflows(sme_id)

    f_node = make_f_auditor_node()
    g_node = make_g_reporter_node()
    hub_node = make_hub_writer_node()

    artifact_f: str | None = None
    artifact_g: str | None = None

    # ── Agent F ────────────────────────────────────────────────────────────
    ctx_f: dict[str, Any] = {
        "sme_id": sme_id,
        "ledger_snapshot": ledger_snapshot,
        "raw_ledger_data": raw_ledger_data,
        "tax_regime": "COMPREHENSIVE",
        "audit_period_days": 365,
    }
    state = _make_state(ctx_f)

    f_update = await f_node(state)
    state["context"] = f_update.get("context", state["context"])
    state["messages"] = state["messages"] + f_update.get("messages", [])

    hub_f_update = await hub_node(state)
    if hub_f_update:
        state["context"] = hub_f_update.get("context", state["context"])
    artifact_f = state["context"].get("hub_artifact_id")

    # ── Agent G ────────────────────────────────────────────────────────────
    # Clear F-specific keys so hub_writer writes G's slot on next call.
    ctx_g: dict[str, Any] = {
        k: v for k, v in state["context"].items()
        if k not in ("audit_result", "hub_artifact_id")
    }
    ctx_g["sme_id"] = sme_id
    ctx_g["raw_ledger_data"] = raw_ledger_data
    state["context"] = ctx_g

    g_update = await g_node(state)
    state["context"] = g_update.get("context", state["context"])
    state["messages"] = state["messages"] + g_update.get("messages", [])

    hub_g_update = await hub_node(state)
    if hub_g_update:
        state["context"] = hub_g_update.get("context", state["context"])
    artifact_g = state["context"].get("hub_artifact_id")

    return {
        "sme_id": sme_id,
        "agent_f_artifact_id": artifact_f,
        "agent_g_artifact_id": artifact_g,
        "status": "ok" if (artifact_f and artifact_g) else "partial",
    }


# ── Celery task ───────────────────────────────────────────────────────────────

@celery_app.task(  # type: ignore[untyped-decorator]
    name="reporting.generate_monthly_intelligence_report",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    queue="batch_processing",
)
def generate_monthly_intelligence_report(self: Any, sme_id: str) -> dict[str, Any]:
    """
    Generate a monthly AI intelligence report for the given SME.

    Runs Agent F (Tax Auditor) and Agent G (Credit Strategist) sequentially
    in a fresh event loop and persists both artifacts to MongoDB
    intelligence_hub.  Returns the artifact IDs so the frontend can poll
    GET /api/agents/intelligence/hub/{artifact_id} for each result.

    Args:
        sme_id: The SME's identifier (used for scoping DB queries).

    Returns:
        {
            "sme_id": str,
            "agent_f_artifact_id": str | None,
            "agent_g_artifact_id": str | None,
            "status": "ok" | "partial",
        }

    Raises:
        Retries up to 3 times on any unhandled exception, with a 60-second
        delay between attempts.
    """
    try:
        return asyncio.run(_run_intelligence_report(sme_id))
    except Exception as exc:
        raise self.retry(exc=exc) from exc


# ── Monthly report dispatcher ─────────────────────────────────────────────────

async def _fetch_all_customer_ids() -> list[str]:
    """Return all customer IDs from PostgreSQL."""
    sql = text("SELECT id::text FROM customers ORDER BY created_at ASC")
    async with AsyncSessionLocal() as session:
        result = await session.execute(sql)
        return [row[0] for row in result.fetchall()]


@celery_app.task(  # type: ignore[untyped-decorator]
    name="reporting.dispatch_monthly_reports",
    queue="batch_processing",
)
def dispatch_monthly_reports() -> dict[str, Any]:
    """
    Fired by Celery beat on the first of each month (UTC midnight).

    Fetches all customer IDs and enqueues one
    ``reporting.generate_monthly_intelligence_report`` task per customer so
    Agent F + G run for every SME without blocking the beat thread.

    Returns:
        {"dispatched": int}  — number of per-customer tasks enqueued.
    """
    customer_ids: list[str] = asyncio.run(_fetch_all_customer_ids())
    for cid in customer_ids:
        generate_monthly_intelligence_report.delay(cid)
    logger.info("Monthly report dispatch complete", dispatched=len(customer_ids))
    return {"dispatched": len(customer_ids)}
