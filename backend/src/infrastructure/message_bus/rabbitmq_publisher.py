import json
from typing import Any

import aio_pika
from aio_pika import ExchangeType
from aio_pika.abc import AbstractRobustConnection

from src.core.config import settings
from src.core.logging import logger

_connection: AbstractRobustConnection | None = None


async def init_rabbitmq() -> None:
    global _connection
    _connection = await aio_pika.connect_robust(settings.RABBITMQ_URL)


async def close_rabbitmq() -> None:
    if _connection and not _connection.is_closed:
        await _connection.close()


async def publish(exchange_name: str, routing_key: str, payload: dict[str, Any]) -> None:
    if _connection is None or _connection.is_closed:
        logger.warning("RabbitMQ connection unavailable; skipping publish", routing_key=routing_key)
        return
    async with _connection.channel() as channel:
        exchange = await channel.declare_exchange(exchange_name, ExchangeType.TOPIC, durable=True)
        message = aio_pika.Message(
            body=json.dumps(payload).encode(),
            content_type="application/json",
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
        )
        await exchange.publish(message, routing_key=routing_key)
