"""
Transactional outbox projector.

Polls the outbox table for unpublished events and forwards them to RabbitMQ,
guaranteeing at-least-once delivery without distributed transactions.
"""
import asyncio
import time

from sqlalchemy import func, select, update

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
    async with AsyncSessionLocal() as session:
        # Lazy import to avoid circular deps at module load time
        from src.domains.finance.models import OutboxEvent  # noqa: PLC0415

        # Snapshot the pending backlog for the gauge before consuming any rows.
        pending_count: int = (
            await session.scalar(
                select(func.count()).select_from(OutboxEvent).where(OutboxEvent.published == False)  # noqa: E712
            )
        ) or 0
        OUTBOX_PENDING_EVENTS.set(pending_count)

        result = await session.execute(
            select(OutboxEvent).where(OutboxEvent.published == False).limit(100)  # noqa: E712
        )
        events = result.scalars().all()
        for event in events:
            await publish(
                exchange_name=event.exchange,
                routing_key=event.routing_key,
                payload=event.payload,
            )
            await session.execute(
                update(OutboxEvent)
                .where(OutboxEvent.id == event.id)
                .values(published=True)
            )
            OUTBOX_EVENTS_PUBLISHED.inc()
        await session.commit()

    _elapsed = time.monotonic() - _t0
    OUTBOX_SYNC_DURATION.observe(_elapsed)
    OUTBOX_SYNC_LATENCY.observe(_elapsed)  # D3-spec canonical name
    return len(events)


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
