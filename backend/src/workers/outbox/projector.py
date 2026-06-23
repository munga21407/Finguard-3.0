"""
Transactional outbox projector.

Polls the outbox table for unpublished events and forwards them to RabbitMQ,
guaranteeing at-least-once delivery without distributed transactions.

Per-event failure isolation
---------------------------
Each `project_once()` call locks a batch of pending rows (FOR UPDATE SKIP LOCKED
so concurrent workers grab disjoint sets) and then publishes them **one at a
time, each in its own try/except**:

  * Success → `event.published = True`.
  * Broker failure → `retry_count += 1`, `last_error` recorded; the failure is
    swallowed so it CANNOT roll back the events that already published in this
    batch.  The event stays PENDING and is retried next poll.
  * Once `retry_count` reaches `OUTBOX_MAX_RETRIES` the event is **moved** to the
    `outbox_dead_letters` table (copied, then deleted) so a single poison message
    never blocks the pipeline or re-enters the publish loop.

All of the above — the `published` flags, the `retry_count`/`last_error` bumps,
and the dead-letter moves — commit together at the end of the batch.  Because
broker failures are caught per-event (never raised), a poison message no longer
rolls back its healthy batch-mates.

At-least-once delivery is preserved: if the process crashes after a broker ACK
but before the DB commit, the event stays PENDING and is republished next poll.
Consumer-side idempotency keys are the correct complement to this design.
"""
import asyncio
import time

from sqlalchemy import func, select

from src.core.config import settings
from src.core.logging import logger
from src.core.metrics import (
    OUTBOX_EVENTS_DEAD_LETTERED,
    OUTBOX_EVENTS_PUBLISHED,
    OUTBOX_EVENTS_RETRIED,
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
        from src.domains.finance.models import (  # noqa: PLC0415
            OutboxDeadLetter,
            OutboxEvent,
        )

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
                try:
                    await publish(
                        exchange_name=event.exchange,
                        routing_key=event.routing_key,
                        payload=event.payload,
                    )
                except Exception as exc:  # noqa: BLE001 — isolate one event's failure
                    # Caught per-event so a poison message cannot roll back the
                    # healthy events that already published in this same batch.
                    event.retry_count += 1
                    event.last_error = repr(exc)[:1000]
                    OUTBOX_EVENTS_RETRIED.inc()
                    if event.retry_count >= settings.OUTBOX_MAX_RETRIES:
                        # Exhausted retries → move out of the pipeline so it stops
                        # blocking / re-entering the publish loop.
                        session.add(
                            OutboxDeadLetter(
                                original_event_id=event.id,
                                exchange=event.exchange,
                                routing_key=event.routing_key,
                                payload=event.payload,
                                retry_count=event.retry_count,
                                last_error=event.last_error,
                                original_created_at=event.created_at,
                            )
                        )
                        await session.delete(event)
                        OUTBOX_EVENTS_DEAD_LETTERED.inc()
                        logger.error(
                            "Outbox event dead-lettered after exhausting retries",
                            event_id=str(event.id),
                            routing_key=event.routing_key,
                            retry_count=event.retry_count,
                            last_error=event.last_error,
                        )
                    else:
                        logger.warning(
                            "Outbox publish failed; will retry",
                            event_id=str(event.id),
                            routing_key=event.routing_key,
                            retry_count=event.retry_count,
                            max_retries=settings.OUTBOX_MAX_RETRIES,
                        )
                    continue

                # Mark via ORM dirty-tracking; flushed atomically at commit.
                event.published = True
                published_count += 1
                OUTBOX_EVENTS_PUBLISHED.inc()

            # session.begin() commits here: published flags, retry bumps, and
            # dead-letter moves all persist together.

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
