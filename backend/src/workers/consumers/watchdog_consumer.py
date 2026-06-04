"""
Agent E RabbitMQ consumer.

Listens on `finguard.agent_e.events` queue (bound to the `finguard.events`
TOPIC exchange, routing key `expenses.created`).  For each message:

  1. Validates idempotency via Redis — skips already-processed expense IDs.
  2. Extracts the expense payload.
  3. Calls Agent E's watchdog logic with a fresh OrchestratorState.
  4. ack() on success, nack(requeue=False) on unrecoverable error.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

import aio_pika
from aio_pika.abc import AbstractIncomingMessage
from langchain_core.messages import HumanMessage

from src.core.config import settings
from src.core.logging import logger
from src.core.metrics import AMQP_MESSAGES_CONSUMED
from src.domains.intelligence.agents.e_watchdog import make_e_watchdog_node
from src.domains.intelligence.agents.hub_writer import make_hub_writer_node
from src.infrastructure.cache.redis import get_redis

EXCHANGE = "finguard.events"
QUEUE = "finguard.agent_e.events"
ROUTING_KEY = "expenses.created"
IDEMPOTENCY_TTL = 86_400          # 24 hours — prevent reprocessing after broker restart
IDEMPOTENCY_PREFIX = "processed:expenses:"

# Dead-letter exchange: messages that fail processing are routed here
# instead of being requeued indefinitely (prevents poison-message storms)
DLQ_EXCHANGE = "finguard.events.dlq"
DLQ_QUEUE = "finguard.agent_e.events.dlq"
DLQ_ROUTING_KEY = f"dlq.{ROUTING_KEY}"
MESSAGE_TTL_MS = 86_400_000       # 24h in milliseconds — messages expire from main queue


async def _is_processed(expense_id: str) -> bool:
    """Return True if this expense was already processed (idempotency guard)."""
    redis = get_redis()
    return bool(await redis.exists(f"{IDEMPOTENCY_PREFIX}{expense_id}"))


async def _mark_processed(expense_id: str) -> None:
    redis = get_redis()
    await redis.setex(f"{IDEMPOTENCY_PREFIX}{expense_id}", IDEMPOTENCY_TTL, "1")


async def _handle_expense_created(body: dict[str, Any]) -> None:
    """
    Unpack an `expenses.created` payload, build a minimal OrchestratorState,
    and invoke Agent E's watchdog node.
    """
    payload = body.get("payload", {})
    expense_id = str(payload.get("expense_id", "unknown"))
    sme_id = str(payload.get("sme_id", ""))
    amount = float(payload.get("amount", 0.0))

    # Build a minimal OrchestratorState for Agent E
    state = {
        "messages": [HumanMessage(content=f"Expense created: {expense_id}")],
        "error_messages": [],
        "next": "e_watchdog",
        "context": {
            "account_id": sme_id,
            "watchdog_period_days": 30,
            "candidate_invoice": {
                "vendor": sme_id,
                "amount": amount,
                "invoice_number": expense_id,
            },
        },
        "session_id": expense_id,
        "user_id": None,
        "mode": "actions",
    }

    node = make_e_watchdog_node()
    result = await node(state)

    # Merge the updated context back into state and persist to intelligence_hub
    updated_state = {
        **state,
        "context": result.get("context", state["context"]),
        "messages": state["messages"] + result.get("messages", []),
    }
    hub_node = make_hub_writer_node()
    await hub_node(updated_state)

    analysis = result.get("context", {}).get("budget_watchdog_result", {})
    logger.info(
        "Watchdog analysis complete",
        expense_id=expense_id,
        current_state=analysis.get("current_state"),
        anomaly_detected=analysis.get("anomaly_detected"),
        vc_id=analysis.get("vc_id"),
    )


async def _process_message(message: AbstractIncomingMessage) -> None:
    try:
        body = json.loads(message.body)
    except json.JSONDecodeError:
        logger.error("Watchdog consumer: malformed JSON — discarding", body=message.body[:200])
        await message.nack(requeue=False)
        return

    payload = body.get("payload", {})
    expense_id = str(payload.get("expense_id", ""))

    if not expense_id:
        logger.warning("Watchdog consumer: missing expense_id — discarding")
        await message.nack(requeue=False)
        return

    # Idempotency check
    if await _is_processed(expense_id):
        logger.info("Watchdog consumer: duplicate message — skipping", expense_id=expense_id)
        await message.ack()
        AMQP_MESSAGES_CONSUMED.labels(queue=QUEUE, status="skipped").inc()
        return

    try:
        await _handle_expense_created(body)
        await _mark_processed(expense_id)
        await message.ack()
        AMQP_MESSAGES_CONSUMED.labels(queue=QUEUE, status="processed").inc()
    except asyncio.CancelledError:
        # Propagate to let the consumer loop shut down cleanly
        raise
    except Exception as exc:
        logger.exception(
            "Watchdog consumer: processing error — dead-lettering",
            expense_id=expense_id,
            error=str(exc),
        )
        await message.nack(requeue=False)
        AMQP_MESSAGES_CONSUMED.labels(queue=QUEUE, status="error").inc()


async def run_watchdog_consumer() -> None:
    """
    Start the aio-pika consumer loop.  Uses `connect_robust` so the connection
    automatically recovers from broker restarts.

    Infrastructure setup on each (re)connect:
      - Declares the primary TOPIC exchange (finguard.events) and the main queue.
      - Declares a Dead-Letter Exchange (DLQ) and binds a DLQ queue to it so
        nack(requeue=False) messages land in finguard.agent_e.events.dlq for
        manual inspection rather than being silently discarded.
      - Sets prefetch_count=1 so a single slow watchdog run never blocks the channel.

    Idempotency uses Redis DB 0 (get_redis() → _pool → REDIS_URL/0).
    """
    logger.info("Starting Agent E expense consumer", queue=QUEUE)
    connection = await aio_pika.connect_robust(
        settings.RABBITMQ_URL,
        reconnect_interval=settings.RABBITMQ_CONSUMER_RETRY_SECONDS,
    )
    async with connection:
        channel = await connection.channel()
        await channel.set_qos(prefetch_count=1)  # one message at a time

        # ── Primary exchange ──────────────────────────────────────────────
        exchange = await channel.declare_exchange(
            EXCHANGE, aio_pika.ExchangeType.TOPIC, durable=True
        )

        # ── Dead-letter exchange + queue ──────────────────────────────────
        dlq_exchange = await channel.declare_exchange(
            DLQ_EXCHANGE, aio_pika.ExchangeType.TOPIC, durable=True
        )
        dlq_queue = await channel.declare_queue(DLQ_QUEUE, durable=True)
        await dlq_queue.bind(dlq_exchange, routing_key=DLQ_ROUTING_KEY)

        # ── Main consumer queue with DLQ routing ──────────────────────────
        queue = await channel.declare_queue(
            QUEUE,
            durable=True,
            arguments={
                "x-dead-letter-exchange": DLQ_EXCHANGE,
                "x-dead-letter-routing-key": DLQ_ROUTING_KEY,
                "x-message-ttl": MESSAGE_TTL_MS,
            },
        )
        await queue.bind(exchange, routing_key=ROUTING_KEY)

        logger.info(
            "Agent E consumer ready",
            queue=QUEUE,
            routing_key=ROUTING_KEY,
            dlq=DLQ_QUEUE,
        )
        async with queue.iterator() as it:
            async for message in it:
                await _process_message(message)


if __name__ == "__main__":
    asyncio.run(run_watchdog_consumer())
