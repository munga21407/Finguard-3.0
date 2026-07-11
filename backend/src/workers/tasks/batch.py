"""
Batch processing Celery tasks.

classify_unclassified_ledger_entries:
  Sweeps ledger_entries WHERE category IS NULL, batches them (up to 50) to
  the model for zero-shot classification, persists the results, and publishes a
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
from sqlalchemy import CursorResult, text

from src.core.config import settings
from src.core.logging import logger
from src.domains.intelligence.agents.hub_writer import make_hub_writer_node
from src.domains.intelligence.llm_client import generate_structured_content
from src.domains.intelligence.ml.model_store import save_model, train_isolation_forest
from src.domains.intelligence.prompts.b_classifier import CLASSIFIER_SYSTEM, TRANSACTION_TAXONOMY
from src.domains.intelligence.schemas import BatchClassificationResult, TransactionClassification
from src.infrastructure.database.mongodb import init_mongo
from src.infrastructure.database.postgres import AsyncSessionLocal
from src.workers.tasks.celery_app import celery_app

_BATCH_SIZE = 50
_EVENT_EXCHANGE = "finguard.events"
_EVENT_ROUTING_KEY = "finance.transactions.classified"
# Trailing window of categorized transactions Agent E's anomaly model trains on.
_AGENT_E_TRAIN_DAYS = 90
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


# ── the model classification (own copy — avoids circular import with b_classifier) ──

async def _classify_batch_async(
    entries: list[dict[str, Any]],
) -> list[TransactionClassification]:
    """Zero-shot classify a batch of raw ledger entries via model structured output."""
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

    result = await generate_structured_content(
        prompt, BatchClassificationResult, temperature=0.0
    )

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
      2. Classify via model.
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
            logger.error("Batch classification: the model call failed", error=str(exc))
            return {"status": "llm_error", "classified": 0, "error": str(exc)}

        # Step 3 — persist.  CAST(:id AS uuid) not :id::uuid — text()'s bind
        # scanner mis-parses a ``:name`` immediately followed by ``::``.
        update_sql = text("""
            UPDATE ledger_entries
            SET category = :category
            WHERE id = CAST(:id AS uuid)
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
    Sweep ledger_entries for unclassified rows, classify with the model, and persist.

    Idempotent: FOR UPDATE SKIP LOCKED ensures concurrent workers each process
    a disjoint batch — no entry is classified twice.

    Returns:
        {
            "status": "ok" | "no_work" | "llm_error",
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
    routing_key: str = "finance.reconciliation.completed",
) -> None:
    """
    Publish a reconciliation-completed domain event to finguard.events.

    ``routing_key`` (and the mirrored ``event_name``) distinguishes the M-Pesa
    sweep from the bank-statement sweep.  Opens a fresh aio-pika connection per
    call (same pattern as _publish_classified_event) so the Celery worker process
    does not depend on the FastAPI lifespan connection singleton.
    """
    payload = {
        "event_name": routing_key,
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
            await exchange.publish(message, routing_key=routing_key)
            logger.info(
                "Published reconciliation event",
                routing_key=routing_key,
                total=total,
                matched=matched_exact + matched_fuzzy,
            )
    except Exception as exc:
        logger.warning(
            "Failed to publish reconciliation event",
            routing_key=routing_key,
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


# ── Core async bank-reconciliation pipeline ───────────────────────────────────

async def _run_batch_bank_reconciliation_async() -> dict[str, Any]:
    """
    Bank-statement reconciliation pipeline (bank_statement_lines → invoices).

    Mirrors ``_run_batch_reconciliation_async`` but delegates to Agent C's
    ``run_bank_reconciliation`` and publishes finance.bank_reconciliation.completed.
    """
    await init_mongo()

    from src.domains.intelligence.agents.c_reconciler import (  # noqa: PLC0415
        run_bank_reconciliation,
    )

    async with AsyncSessionLocal() as session:
        report = await run_bank_reconciliation(session)

    if report.total_transactions == 0:
        return {"status": "no_work", "matched": 0, "unmatched": 0}

    await _publish_reconciliation_event(
        total=report.total_transactions,
        matched_exact=report.matched_exact,
        matched_fuzzy=report.matched_fuzzy,
        unmatched=report.unmatched,
        run_at=report.run_at,
        routing_key="finance.bank_reconciliation.completed",
    )

    artifact_id = await _write_to_hub({
        "bank_reconciliation_report": report.model_dump(),
    })

    logger.info(
        "Batch bank reconciliation completed",
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


@celery_app.task(  # type: ignore[untyped-decorator]
    bind=True,
    name="batch.run_batch_bank_reconciliation",
    queue="batch_processing",
    max_retries=3,
    default_retry_delay=120,
)
def run_batch_bank_reconciliation(self: Any) -> dict[str, Any]:
    """
    Sweep unreconciled bank statement lines, match them to open invoices via
    Agent C's two-pass algorithm (recording Payment(vault=BANK) per match), and
    publish a finance.bank_reconciliation.completed domain event.

    Idempotent: FOR UPDATE SKIP LOCKED inside Agent C ensures concurrent workers
    each process a disjoint batch — no bank line is matched twice.
    """
    try:
        return asyncio.run(_run_batch_bank_reconciliation_async())
    except Exception as exc:
        raise self.retry(exc=exc) from exc


# ── Agent E model retraining ──────────────────────────────────────────────────
#
# Periodic retraining loop for Agent E's per-customer IsolationForest. Each model
# is fit on the trailing _AGENT_E_TRAIN_DAYS of *categorized* debit transactions
# (Agent B sets `category`) and upserted to finguard.agent_e_models by customer.
# The watchdog loads these at scoring time; this removes the on-the-fly fit from
# the hot path for every customer that has any history.

async def _fetch_categorized_customer_ids(session: Any) -> list[str]:
    """Customers with categorized debits in the training window (one model each)."""
    result = await session.execute(
        text("""
            SELECT DISTINCT account_id::text
            FROM ledger_entries
            WHERE transaction_type = 'DEBIT'
              AND category IS NOT NULL
              AND account_id IS NOT NULL
              AND created_at >= NOW() - make_interval(days => :days)
        """),
        {"days": _AGENT_E_TRAIN_DAYS},
    )
    return [row[0] for row in result.fetchall()]


async def _fetch_customer_debit_amounts(session: Any, customer_id: str) -> list[float]:
    result = await session.execute(
        text("""
            SELECT amount::float
            FROM ledger_entries
            WHERE transaction_type = 'DEBIT'
              AND category IS NOT NULL
              AND account_id = CAST(:cid AS uuid)
              AND created_at >= NOW() - make_interval(days => :days)
            ORDER BY created_at DESC
        """),
        {"cid": customer_id, "days": _AGENT_E_TRAIN_DAYS},
    )
    return [float(row[0]) for row in result.fetchall()]


async def _train_and_upsert_customer(session: Any, customer_id: str) -> bool:
    """Fit IsolationForest(contamination='auto') for one customer and upsert it.

    Returns ``True`` when a model was trained+stored, ``False`` when the customer
    had too few samples (left to the watchdog's on-the-fly fallback).
    """
    amounts = await _fetch_customer_debit_amounts(session, customer_id)
    model = train_isolation_forest(amounts)
    if model is None:
        return False
    await save_model(session, uuid.UUID(customer_id), model, len(amounts))
    return True


async def _retrain_agent_e_async() -> dict[str, Any]:
    trained = 0
    skipped = 0
    async with AsyncSessionLocal() as session:
        customer_ids = await _fetch_categorized_customer_ids(session)
        for customer_id in customer_ids:
            if await _train_and_upsert_customer(session, customer_id):
                trained += 1
            else:
                skipped += 1

    logger.info(
        "Agent E retraining complete",
        customers=len(customer_ids),
        trained=trained,
        skipped=skipped,
        window_days=_AGENT_E_TRAIN_DAYS,
    )
    return {
        "status": "ok",
        "customers": len(customer_ids),
        "trained": trained,
        "skipped_insufficient_samples": skipped,
    }


async def _fit_one_agent_e_async(customer_id: str) -> dict[str, Any]:
    async with AsyncSessionLocal() as session:
        trained = await _train_and_upsert_customer(session, customer_id)
    logger.info("Agent E single-customer fit", customer_id=customer_id, trained=trained)
    return {
        "status": "ok" if trained else "insufficient_samples",
        "customer_id": customer_id,
        "trained": trained,
    }


@celery_app.task(  # type: ignore[untyped-decorator]
    bind=True,
    name="batch.retrain_agent_e_models",
    queue="batch_processing",
    max_retries=2,
    default_retry_delay=300,
)
def retrain_agent_e_models(self: Any) -> dict[str, Any]:
    """Weekly retrain of every customer's Agent E IsolationForest.

    Fired by Celery beat. Fits each customer on the trailing 90 days of
    categorized debits and upserts to finguard.agent_e_models; customers with
    too few samples are skipped (handled by the watchdog's on-the-fly fallback).
    """
    try:
        return asyncio.run(_retrain_agent_e_async())
    except Exception as exc:
        raise self.retry(exc=exc) from exc


@celery_app.task(  # type: ignore[untyped-decorator]
    bind=True,
    name="batch.fit_agent_e_model",
    queue="batch_processing",
    max_retries=2,
    default_retry_delay=120,
)
def fit_agent_e_model(self: Any, customer_id: str) -> dict[str, Any]:
    """Fit + persist a single customer's model on demand.

    Enqueued by the watchdog the first time it scores a customer that has no
    persisted model yet, so subsequent runs use the trained weights. Idempotent
    (upsert), so duplicate enqueues are harmless.
    """
    try:
        return asyncio.run(_fit_one_agent_e_async(customer_id))
    except Exception as exc:
        raise self.retry(exc=exc) from exc
