import json
from typing import Any

import aio_pika
from aio_pika import ExchangeType
from aio_pika.abc import AbstractRobustConnection

from src.core.config import settings
from src.core.logging import logger

_connection: AbstractRobustConnection | None = None


class BrokerUnavailableError(RuntimeError):
    """
    Raised when a publish is attempted but the RabbitMQ connection is missing
    or closed.

    This MUST propagate (never be swallowed) so the transactional-outbox
    projector's ``session.begin()`` block rolls back and the event stays
    ``published = False`` for retry on the next poll cycle.  Silently skipping
    a publish here would mark an event delivered when the broker never received
    it — breaking the at-least-once delivery guarantee.
    """


async def init_rabbitmq() -> None:
    global _connection
    _connection = await aio_pika.connect_robust(settings.RABBITMQ_URL)


async def close_rabbitmq() -> None:
    if _connection and not _connection.is_closed:
        await _connection.close()


def is_rabbitmq_connected() -> bool:
    """True when the robust connection is initialised and open.

    Used by the readiness probe. Cheap and synchronous — aio-pika's robust
    connection auto-reconnects in the background, so this reflects current link
    health without issuing a network round-trip.
    """
    return _connection is not None and not _connection.is_closed


async def publish(exchange_name: str, routing_key: str, payload: dict[str, Any]) -> None:
    if _connection is None or _connection.is_closed:
        logger.error(
            "RabbitMQ connection unavailable; raising so the outbox transaction rolls back",
            routing_key=routing_key,
        )
        raise BrokerUnavailableError(
            f"RabbitMQ connection unavailable; cannot publish routing_key={routing_key!r}"
        )
    async with _connection.channel() as channel:
        exchange = await channel.declare_exchange(exchange_name, ExchangeType.TOPIC, durable=True)
        message = aio_pika.Message(
            body=json.dumps(payload).encode(),
            content_type="application/json",
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
        )
        await exchange.publish(message, routing_key=routing_key)
