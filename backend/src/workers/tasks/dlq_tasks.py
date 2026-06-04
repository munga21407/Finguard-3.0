"""
Dead Letter Queue (DLQ) sweep and replay task.

Drains up to ``batch_size`` messages from ``finguard.agent_e.events.dlq``
and republishes eligible ones back to the primary ``finguard.events``
exchange so the watchdog consumer can process them again.

Safety contract
---------------
A DLQ message is ``ack``-ed only **after** it has been successfully
republished to the primary exchange.  If the republish call raises, the
message is ``nack``-ed with ``requeue=True`` so it stays in the DLQ for
the next sweep — it is **never** silently dropped.

Poison-message guard
--------------------
If a message has accumulated more than ``MAX_DEATH_COUNT`` dead-letter
events (summed across all queues in the ``x-death`` header), it is
discarded with a warning log and acknowledged so it does not block the
queue indefinitely.

Scheduling
----------
Registered in Celery beat as ``dlq.drain_watchdog_dlq`` running every
15 minutes.  Can also be triggered manually:

    celery -A src.workers.tasks.celery_app call dlq.drain_watchdog_dlq
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

import aio_pika
import structlog

from src.core.config import settings
from src.workers.tasks.celery_app import celery_app

logger = structlog.get_logger(__name__)

# ── DLQ topology — mirrors watchdog_consumer.py constants ─────────────────────
_PRIMARY_EXCHANGE = "finguard.events"
_PRIMARY_ROUTING_KEY = "expenses.created"         # original routing key to restore
_DLQ_EXCHANGE = "finguard.events.dlq"
_DLQ_QUEUE = "finguard.agent_e.events.dlq"
_DLQ_ROUTING_KEY = f"dlq.{_PRIMARY_ROUTING_KEY}"

_DEFAULT_BATCH_SIZE = 100
MAX_DEATH_COUNT = 3   # discard messages that have died more than this many times


# ---------------------------------------------------------------------------
# x-death header helpers
# ---------------------------------------------------------------------------

def _get_death_count(headers: dict[str, Any]) -> int:
    """
    Return the total number of times this message has been dead-lettered.

    RabbitMQ appends one entry to ``x-death`` per (queue, reason) pair,
    incrementing the ``count`` field on repeat deaths.  Summing all counts
    gives the true total across every queue the message has died in.
    """
    x_death = headers.get("x-death", [])
    if not isinstance(x_death, list):
        return 0
    return sum(
        int(entry.get("count", 1))
        for entry in x_death
        if isinstance(entry, dict)
    )


def _extract_death_reasons(headers: dict[str, Any]) -> list[dict[str, Any]]:
    """Return a structured summary of every death event for logging."""
    x_death = headers.get("x-death", [])
    if not isinstance(x_death, list):
        return []
    reasons: list[dict[str, Any]] = []
    for entry in x_death:
        if not isinstance(entry, dict):
            continue
        reasons.append({
            "queue":        entry.get("queue", "unknown"),
            "exchange":     entry.get("exchange", "unknown"),
            "routing_keys": entry.get("routing-keys", []),
            "reason":       entry.get("reason", "unknown"),
            "count":        entry.get("count", 1),
        })
    return reasons


# ---------------------------------------------------------------------------
# Core async drain
# ---------------------------------------------------------------------------

async def _drain_dlq(batch_size: int) -> dict[str, int]:
    """
    Open a short-lived aio-pika connection, drain up to ``batch_size``
    messages from the DLQ, and close the connection.

    Returns a stats dict:
        {
            "replayed":  int,  # successfully republished and acked
            "discarded": int,  # exceeded MAX_DEATH_COUNT — acked without replay
            "skipped":   int,  # republish failed — left in DLQ (nacked)
            "total":     int,
        }
    """
    replayed = discarded = skipped = 0

    connection = await aio_pika.connect_robust(
        settings.RABBITMQ_URL,
        reconnect_interval=5,
    )
    async with connection:
        channel = await connection.channel()
        await channel.set_qos(prefetch_count=batch_size)

        # ── Declare topology (idempotent) ─────────────────────────────────────
        primary_exchange = await channel.declare_exchange(
            _PRIMARY_EXCHANGE, aio_pika.ExchangeType.TOPIC, durable=True
        )
        dlq_exchange = await channel.declare_exchange(
            _DLQ_EXCHANGE, aio_pika.ExchangeType.TOPIC, durable=True
        )
        dlq_queue = await channel.declare_queue(_DLQ_QUEUE, durable=True)
        await dlq_queue.bind(dlq_exchange, routing_key=_DLQ_ROUTING_KEY)

        logger.info(
            "dlq_drain: starting sweep",
            queue=_DLQ_QUEUE,
            batch_size=batch_size,
        )

        for _ in range(batch_size):
            # Non-blocking read — returns None when the queue is empty.
            message: aio_pika.abc.AbstractIncomingMessage | None = (
                await dlq_queue.get(fail=False)
            )
            if message is None:
                break  # DLQ is drained

            headers: dict[str, Any] = dict(message.headers or {})
            death_count = _get_death_count(headers)
            death_reasons = _extract_death_reasons(headers)

            # ── Poison-message guard ──────────────────────────────────────────
            if death_count > MAX_DEATH_COUNT:
                logger.warning(
                    "dlq_drain: discarding poison message — death count exceeded",
                    queue=_DLQ_QUEUE,
                    death_count=death_count,
                    max_allowed=MAX_DEATH_COUNT,
                    death_reasons=death_reasons,
                    body_preview=message.body[:200].decode("utf-8", errors="replace"),
                )
                await message.ack()
                discarded += 1
                continue

            # ── Log failure history ───────────────────────────────────────────
            try:
                body_preview = json.loads(message.body).get("payload", {}).get("expense_id", "?")
            except Exception:
                body_preview = message.body[:80].decode("utf-8", errors="replace")

            logger.info(
                "dlq_drain: replaying message",
                queue=_DLQ_QUEUE,
                expense_id=body_preview,
                death_count=death_count,
                death_reasons=death_reasons,
                target_exchange=_PRIMARY_EXCHANGE,
                target_routing_key=_PRIMARY_ROUTING_KEY,
            )

            # ── Republish to primary exchange ─────────────────────────────────
            # Strip x-death headers so the republished message starts with a
            # clean slate; the consumer's own idempotency guard will handle
            # duplicates if the same expense_id was previously processed.
            clean_headers = {
                k: v for k, v in headers.items() if k != "x-death"
            }
            outbound = aio_pika.Message(
                body=message.body,
                headers=clean_headers,
                content_type=message.content_type or "application/json",
                delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            )

            try:
                await primary_exchange.publish(outbound, routing_key=_PRIMARY_ROUTING_KEY)
            except Exception as pub_exc:
                # DO NOT ack — leave the message in the DLQ for the next sweep.
                logger.error(
                    "dlq_drain: republish failed — leaving message in DLQ",
                    queue=_DLQ_QUEUE,
                    expense_id=body_preview,
                    error=str(pub_exc),
                    exc_info=True,
                )
                await message.nack(requeue=True)
                skipped += 1
                continue

            # Only ack AFTER the republish succeeded.
            await message.ack()
            replayed += 1

    total = replayed + discarded + skipped
    logger.info(
        "dlq_drain: sweep complete",
        queue=_DLQ_QUEUE,
        replayed=replayed,
        discarded=discarded,
        skipped=skipped,
        total=total,
    )
    return {"replayed": replayed, "discarded": discarded, "skipped": skipped, "total": total}


# ---------------------------------------------------------------------------
# Celery task
# ---------------------------------------------------------------------------

@celery_app.task(  # type: ignore[untyped-decorator]
    name="dlq.drain_watchdog_dlq",
    queue="batch_processing",
    max_retries=0,         # DLQ drain is idempotent; unacked messages stay safe
    ignore_result=False,
)
def drain_watchdog_dlq(batch_size: int = _DEFAULT_BATCH_SIZE) -> dict[str, int]:
    """
    Celery task: sweep the watchdog Dead Letter Queue and replay eligible messages.

    Args:
        batch_size: Maximum number of DLQ messages to process per invocation.
                    Defaults to 100. Set lower for more frequent, smaller sweeps.

    Returns:
        {
            "replayed":  int,  # messages successfully returned to primary exchange
            "discarded": int,  # poison messages acked without republishing
            "skipped":   int,  # republish failures — messages left in DLQ
            "total":     int,
        }

    Safety:
        Messages are only acked from the DLQ after a confirmed successful
        republish.  If this task crashes mid-sweep, all unacked messages are
        automatically requeued by RabbitMQ when the channel closes.
    """
    logger.info("dlq_drain: Celery task started", batch_size=batch_size)
    return asyncio.run(_drain_dlq(batch_size))
