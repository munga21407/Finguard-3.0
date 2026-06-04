"""
Transactional outbox projector.

Polls the outbox table for unpublished events and forwards them to RabbitMQ,
guaranteeing at-least-once delivery without distributed transactions.

Race-condition guarantee
------------------------
Each `project_once()` call wraps the SELECT, all broker publishes, and all
`published = True` updates in a single `session.begin()` transaction:

  1. SELECT … FOR UPDATE SKIP LOCKED — concurrent workers each grab a disjoint
     set of rows; no event is processed twice simultaneously.
  2. For each event: publish to broker, then mark `event.published = True`.
     If the broker raises, the exception propagates out of `session.begin()`,
     which issues an automatic ROLLBACK — all events remain published=False
     and will be retried on the next poll cycle.
  3. Only after every event in the batch is successfully published does the
     context manager commit — atomically persisting all `published=True` flags.

This preserves at-least-once delivery: if the process crashes after the broker
ACK but before the DB commit, events will be republished on the next poll.
Consumer-side idempotency keys are the correct complement to this design.
"""
import asyncio
import time

from sqlalchemy import func, select

from src.core.logging import logger
from src.core.metrics import (
    OUTBOX_EVENTS_PUBLISHED,
    OUTBOX_PENDING_EVENTS,
    OUTBOX_SYNC_DURATION,
    OUTBOX_SYNC_LATENCY,
)
from src.infrastructure.database.postgres import AsyncSessionLocal
from src.infrastructure.message_bus.rabbitmq_publisher import publish


async def project_once() -> int:
    _t0 = time.monotonic()
    published_count = 0

    async with AsyncSessionLocal() as session:
        # Lazy import to avoid circular deps at module load time
        from src.domains.finance.models import OutboxEvent  # noqa: PLC0415

        async with session.begin():
            # Snapshot the pending backlog for the gauge (approximate; READ COMMITTED).
            pending_count: int = (
                await session.scalar(
                    select(func.count())
                    .select_from(OutboxEvent)
                    .where(OutboxEvent.published == False)  # noqa: E712
                )
            ) or 0
            OUTBOX_PENDING_EVENTS.set(pending_count)

            # Lock the rows this worker will process; other workers skip them.
            result = await session.execute(
                select(OutboxEvent)
                .where(OutboxEvent.published == False)  # noqa: E712
                .order_by(OutboxEvent.created_at.asc())
                .limit(100)
                .with_for_update(skip_locked=True)
            )
            events = result.scalars().all()

            for event in events:
                # Publish first.  If the broker raises, the exception propagates
                # out of session.begin() which issues an automatic ROLLBACK —
                # published=True is never persisted and the event stays PENDING.
                await publish(
                    exchange_name=event.exchange,
                    routing_key=event.routing_key,
                    payload=event.payload,
                )
                # Mark via ORM dirty-tracking; flushed atomically at commit.
                event.published = True
                published_count += 1
                OUTBOX_EVENTS_PUBLISHED.inc()

            # session.begin() commits here — only if every publish succeeded.

    _elapsed = time.monotonic() - _t0
    OUTBOX_SYNC_DURATION.observe(_elapsed)
    OUTBOX_SYNC_LATENCY.observe(_elapsed)  # D3-spec canonical name
    return published_count


async def run_projector(interval_seconds: float = 5.0) -> None:
    logger.info("Outbox projector started", interval=interval_seconds)
    while True:
        try:
            count = await project_once()
            if count:
                logger.info("Outbox events published", count=count)
        except Exception:
            logger.exception("Outbox projector error")
        await asyncio.sleep(interval_seconds)
