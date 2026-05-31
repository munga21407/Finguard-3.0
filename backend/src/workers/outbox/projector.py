"""
Transactional outbox projector.

Polls the outbox table for unpublished events and forwards them to RabbitMQ,
guaranteeing at-least-once delivery without distributed transactions.
"""
import asyncio

from sqlalchemy import select, update

from src.core.logging import logger
from src.infrastructure.database.postgres import AsyncSessionLocal
from src.infrastructure.message_bus.publisher import publish


async def project_once() -> int:
    async with AsyncSessionLocal() as session:
        # Lazy import to avoid circular deps at module load time
        from src.domains.finance.models import OutboxEvent  # noqa: PLC0415

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
        await session.commit()
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
