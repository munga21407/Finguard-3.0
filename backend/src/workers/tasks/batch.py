"""
Batch processing Celery tasks.

classify_unclassified_ledger_entries:
  Sweeps ledger_entries WHERE category IS NULL, batches them (up to 50) to
  Gemini for zero-shot classification, persists the results, and publishes a
  finance.transactions.classified domain event.

run_batch_reconciliation:
  Queries all unreconciled M-Pesa transactions and open invoices, calls the
  Agent C core reconciliation pipeline in a loop (100 transactions per batch),
  and publishes a finance.reconciliation.completed domain event on completion.

  Row-locking semantics for both tasks:
    SELECT ... FOR UPDATE SKIP LOCKED  — multiple concurrent workers each grab
    a disjoint batch so no row is processed twice simultaneously.

  Sync → async bridge:
    Celery workers are synchronous; all async work is executed inside a single
    asyncio.run() call, matching the pattern in reporting_tasks.py.
"""
from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime
from typing import Any, cast

import aio_pika
from aio_pika import ExchangeType
from google.genai import types
from sqlalchemy import CursorResult, text

from src.core.config import settings
from src.core.logging import logger
from src.domains.intelligence.agents.hub_writer import make_hub_writer_node
from src.domains.intelligence.llm_client import get_gemini_client
from src.domains.intelligence.prompts.b_classifier import CLASSIFIER_SYSTEM, TRANSACTION_TAXONOMY
from src.domains.intelligence.schemas import BatchClassificationResult, TransactionClassification
from src.infrastructure.database.mongodb import init_mongo
from src.infrastructure.database.postgres import AsyncSessionLocal
from src.workers.tasks.celery_app import celery_app

_BATCH_SIZE = 50
_EVENT_EXCHANGE = "finguard.events"
_EVENT_ROUTING_KEY = "finance.transactions.classified"
# Max rows the weekly data-retention sweep deletes per Celery invocation —
# bounded so the DELETE never takes a long table lock in production.
_RETENTION_BATCH_SIZE = 10_000


async def _write_to_hub(context: dict[str, Any]) -> str | None:
    """Persist an agent output to intelligence_hub; return the artifact_id."""
    hub_node = make_hub_writer_node()
    state: dict[str, Any] = {
        "messages": [],
        "next": "FINISH",
        "context": context,
        "session_id": str(uuid.uuid4()),
        "user_id": None,
        "mode": "actions",
    }
    result = await hub_node(state)
    return (result or {}).get("context", {}).get("hub_artifact_id")


# ── Gemini classification (own copy — avoids circular import with b_classifier) ──

async def _classify_batch_async(
    entries: list[dict[str, Any]],
) -> list[TransactionClassification]:
    """Zero-shot classify a batch of raw ledger entries via Gemini structured output."""
    if not entries:
        return []

    batch_json = json.dumps(entries, indent=2)
    prompt = (
        f"{CLASSIFIER_SYSTEM}\n\n"
        "## Input Transactions (JSON)\n"
        f"{batch_json}\n\n"
        "Classify every transaction in the list above. "
        "Return a JSON object with a 'classifications' array where each element "
        "contains entry_id, category (from the taxonomy), and confidence (0.0–1.0). "
        "Every input entry_id must appear exactly once in the output."
    )

    client = get_gemini_client()
    response = await client.aio.models.generate_content(
        model=settings.GEMINI_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=BatchClassificationResult,
            temperature=0.0,
        ),
    )
    result = BatchClassificationResult.model_validate_json(response.text or "{}")

    returned_ids = {c.entry_id for c in result.classifications}
    for entry in entries:
        if str(entry["entry_id"]) not in returned_ids:
            result.classifications.append(
                TransactionClassification(
                    entry_id=str(entry["entry_id"]), category="other", confidence=0.0
                )
            )

    valid = set(TRANSACTION_TAXONOMY)
    for clf in result.classifications:
        if clf.category not in valid:
            clf.category = "other"
            clf.confidence = 0.0

    return result.classifications


# ── RabbitMQ publish (dedicated connection — not the FastAPI singleton) ────────

async def _publish_classified_event(
    classified_count: int,
    entry_ids: list[str],
) -> None:
    """
    Publish finance.transactions.classified to finguard.events.

    Opens a fresh aio-pika connection per call so the Celery worker process
    does not depend on the FastAPI lifespan connection singleton.
    """
    payload = {
        "event_name": _EVENT_ROUTING_KEY,
        "emitted_at": datetime.now(UTC).isoformat(),
        "payload": {
            "classified_count": classified_count,
            "entry_ids": entry_ids,
        },
    }
    try:
        connection = await aio_pika.connect_robust(settings.RABBITMQ_URL)
        async with connection:
            channel = await connection.channel()
            exchange = await channel.declare_exchange(
                _EVENT_EXCHANGE, ExchangeType.TOPIC, durable=True
            )
            message = aio_pika.Message(
                body=json.dumps(payload).encode(),
                content_type="application/json",
                delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            )
            await exchange.publish(message, routing_key=_EVENT_ROUTING_KEY)
            logger.info(
                "Published finance.transactions.classified event",
                classified_count=classified_count,
            )
    except Exception as exc:
        logger.warning(
            "Failed to publish classification event",
            error=str(exc),
            classified_count=classified_count,
        )


# ── Core async pipeline ────────────────────────────────────────────────────────

async def _run_batch_classification() -> dict[str, Any]:
    """
    Full pipeline executed inside asyncio.run():
      1. Fetch up to _BATCH_SIZE rows with FOR UPDATE SKIP LOCKED.
      2. Classify via Gemini.
      3. Persist categories to ledger_entries.
      4. Publish domain event.
      5. Write artifact to intelligence_hub.
    """
    await init_mongo()
    async with AsyncSessionLocal() as session:
        # Step 1 — fetch with row-level lock to prevent concurrent duplicate work
        fetch_sql = text(f"""
            SELECT id::text, description, amount::float, transaction_type::text
            FROM ledger_entries
            WHERE category IS NULL
            ORDER BY created_at ASC
            LIMIT {_BATCH_SIZE}
            FOR UPDATE SKIP LOCKED
        """)
        result = await session.execute(fetch_sql)
        rows = result.fetchall()

        if not rows:
            return {"status": "no_work", "classified": 0}

        entries = [
            {
                "entry_id": row[0],
                "narrative": row[1] or "",
                "amount": row[2] or 0.0,
                "transaction_type": row[3],
            }
            for row in rows
        ]

        # Step 2 — classify
        try:
            classifications = await _classify_batch_async(entries)
        except Exception as exc:
            logger.error("Batch classification: Gemini call failed", error=str(exc))
            return {"status": "gemini_error", "classified": 0, "error": str(exc)}

        # Step 3 — persist
        update_sql = text("""
            UPDATE ledger_entries
            SET category = :category
            WHERE id = :id::uuid
        """)
        for clf in classifications:
            await session.execute(
                update_sql,
                {"category": clf.category, "id": clf.entry_id},
            )
        await session.commit()

    # Step 4 — publish event (outside session context, connection is closed)
    classified_ids = [clf.entry_id for clf in classifications]
    await _publish_classified_event(len(classified_ids), classified_ids)

    # Step 5 — persist to intelligence_hub so both activation paths are visible
    artifact_id = await _write_to_hub({
        "classified_transactions": [c.model_dump() for c in classifications],
    })

    logger.info(
        "Batch classification completed",
        classified=len(classified_ids),
        artifact_id=artifact_id,
    )
    return {
        "status": "ok",
        "classified": len(classified_ids),
        "entry_ids": classified_ids,
        "hub_artifact_id": artifact_id,
    }


# ── Celery task ────────────────────────────────────────────────────────────────

@celery_app.task(  # type: ignore[untyped-decorator]
    bind=True,
    name="batch.classify_unclassified_ledger_entries",
    queue="batch_processing",
    max_retries=3,
    default_retry_delay=120,
)
def classify_unclassified_ledger_entries(self: Any) -> dict[str, Any]:
    """
    Sweep ledger_entries for unclassified rows, classify with Gemini, and persist.

    Idempotent: FOR UPDATE SKIP LOCKED ensures concurrent workers each process
    a disjoint batch — no entry is classified twice.

    Returns:
        {
            "status": "ok" | "no_work" | "gemini_error",
            "classified": int,
            "entry_ids": list[str],   # present when status == "ok"
        }
    """
    try:
        return asyncio.run(_run_batch_classification())
    except Exception as exc:
        raise self.retry(exc=exc) from exc


# ── Reconciliation event publisher ────────────────────────────────────────────

async def _publish_reconciliation_event(
    total: int,
    matched_exact: int,
    matched_fuzzy: int,
    unmatched: int,
    run_at: str,
) -> None:
    """
    Publish finance.reconciliation.completed to finguard.events.

    Opens a fresh aio-pika connection per call (same pattern as
    _publish_classified_event) so the Celery worker process does not depend
    on the FastAPI lifespan connection singleton.
    """
    payload = {
        "event_name": "finance.reconciliation.completed",
        "emitted_at": datetime.now(UTC).isoformat(),
        "payload": {
            "total_transactions": total,
            "matched_exact": matched_exact,
            "matched_fuzzy": matched_fuzzy,
            "unmatched": unmatched,
            "run_at": run_at,
        },
    }
    try:
        connection = await aio_pika.connect_robust(settings.RABBITMQ_URL)
        async with connection:
            channel = await connection.channel()
            exchange = await channel.declare_exchange(
                _EVENT_EXCHANGE, ExchangeType.TOPIC, durable=True
            )
            message = aio_pika.Message(
                body=json.dumps(payload).encode(),
                content_type="application/json",
                delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            )
            await exchange.publish(
                message, routing_key="finance.reconciliation.completed"
            )
            logger.info(
                "Published finance.reconciliation.completed event",
                total=total,
                matched=matched_exact + matched_fuzzy,
            )
    except Exception as exc:
        logger.warning(
            "Failed to publish reconciliation event",
            error=str(exc),
            total=total,
        )


# ── Core async reconciliation pipeline ────────────────────────────────────────

async def _run_batch_reconciliation_async() -> dict[str, Any]:
    """
    Full reconciliation pipeline executed inside asyncio.run():
      1. Delegate to Agent C's run_reconciliation() for one batch of 100 txns.
      2. Log results and publish the domain event.
      3. Write artifact to intelligence_hub.

    Agent C handles its own session lifecycle and row locking internally;
    this wrapper is responsible only for the event publish and result summary.
    """
    await init_mongo()

    # Lazy import avoids loading agent dependencies at module import time
    from src.domains.intelligence.agents.c_reconciler import run_reconciliation  # noqa: PLC0415

    async with AsyncSessionLocal() as session:
        report = await run_reconciliation(session)

    if report.total_transactions == 0:
        return {"status": "no_work", "matched": 0, "unmatched": 0}

    await _publish_reconciliation_event(
        total=report.total_transactions,
        matched_exact=report.matched_exact,
        matched_fuzzy=report.matched_fuzzy,
        unmatched=report.unmatched,
        run_at=report.run_at,
    )

    # Persist to intelligence_hub so batch path is visible alongside HTTP path
    artifact_id = await _write_to_hub({
        "reconciliation_report": report.model_dump(),
    })

    logger.info(
        "Batch reconciliation completed",
        total=report.total_transactions,
        exact=report.matched_exact,
        fuzzy=report.matched_fuzzy,
        unmatched=report.unmatched,
        artifact_id=artifact_id,
    )
    return {
        "status": "ok",
        "total": report.total_transactions,
        "matched_exact": report.matched_exact,
        "matched_fuzzy": report.matched_fuzzy,
        "unmatched": report.unmatched,
        "run_at": report.run_at,
        "hub_artifact_id": artifact_id,
    }


# ── Data-retention pipeline ───────────────────────────────────────────────────

async def _run_data_retention_async() -> dict[str, Any]:
    """
    Delete ledger_entries older than 7 years in bounded batches.

    Uses a subquery-based DELETE with LIMIT so the operation never holds a
    full-table lock in production.  One Celery invocation removes up to
    ``_RETENTION_BATCH_SIZE`` rows; the beat schedule runs weekly so backlog
    drains incrementally without impacting OLTP throughput.

    Returns:
        {"status": "ok" | "no_work", "deleted_rows": int}
    """
    sql = text(f"""
        DELETE FROM ledger_entries
        WHERE id IN (
            SELECT id
            FROM   ledger_entries
            WHERE  created_at < NOW() - INTERVAL '7 years'
            LIMIT  {_RETENTION_BATCH_SIZE}
        )
    """)

    async with AsyncSessionLocal() as session:
        result = await session.execute(sql)
        await session.commit()
        # A DELETE returns a CursorResult; .rowcount is the deleted row count.
        deleted: int = cast("CursorResult[Any]", result).rowcount

    if deleted == 0:
        logger.info("Data retention: no rows eligible for deletion")
        return {"status": "no_work", "deleted_rows": 0}

    logger.info(
        "Data retention: ledger_entries purge complete",
        deleted_rows=deleted,
        batch_limit=_RETENTION_BATCH_SIZE,
        retention_policy="7 years",
    )
    return {"status": "ok", "deleted_rows": deleted}


@celery_app.task(  # type: ignore[untyped-decorator]
    name="batch.enforce_data_retention",
    queue="batch_processing",
    max_retries=2,
    default_retry_delay=300,
)
def enforce_data_retention() -> dict[str, Any]:
    """
    Scheduled GDPR / DPA data retention sweep.

    Removes ``ledger_entries`` rows older than 7 years in batches of up to
    10 000 rows per invocation to avoid long table-level locks.  Celery beat
    fires this task weekly; run it manually to drain an accumulated backlog:

        celery -A src.workers.tasks.celery_app call batch.enforce_data_retention

    Returns:
        {"status": "ok" | "no_work", "deleted_rows": int}
    """
    return asyncio.run(_run_data_retention_async())


# ── Celery task ────────────────────────────────────────────────────────────────

@celery_app.task(  # type: ignore[untyped-decorator]
    bind=True,
    name="batch.run_batch_reconciliation",
    queue="batch_processing",
    max_retries=3,
    default_retry_delay=120,
)
def run_batch_reconciliation(self: Any) -> dict[str, Any]:
    """
    Sweep unreconciled M-Pesa transactions, match them to open invoices via
    Agent C's two-pass algorithm, update invoice statuses, and publish a
    finance.reconciliation.completed domain event.

    Idempotent: FOR UPDATE SKIP LOCKED inside Agent C ensures concurrent
    workers each process a disjoint batch — no transaction is matched twice.

    Returns:
        {
            "status": "ok" | "no_work",
            "total": int,
            "matched_exact": int,
            "matched_fuzzy": int,
            "unmatched": int,
            "run_at": str,   # present when status == "ok"
        }
    """
    try:
        return asyncio.run(_run_batch_reconciliation_async())
    except Exception as exc:
        raise self.retry(exc=exc) from exc
