"""
Watchdog consumer — monitors system health events from RabbitMQ.
"""
import asyncio
import json

import aio_pika

from src.core.config import settings
from src.core.logging import logger

EXCHANGE = "finguard.system"
QUEUE = "watchdog"
ROUTING_KEY = "system.health.#"


async def handle_message(message: aio_pika.IncomingMessage) -> None:
    async with message.process():
        payload = json.loads(message.body)
        logger.info("Watchdog event received", routing_key=message.routing_key, payload=payload)
        # TODO: implement alerting / auto-remediation logic


async def run_watchdog_consumer() -> None:
    connection = await aio_pika.connect_robust(settings.RABBITMQ_URL)
    async with connection:
        channel = await connection.channel()
        await channel.set_qos(prefetch_count=10)
        exchange = await channel.declare_exchange(EXCHANGE, aio_pika.ExchangeType.TOPIC, durable=True)
        queue = await channel.declare_queue(QUEUE, durable=True)
        await queue.bind(exchange, routing_key=ROUTING_KEY)
        logger.info("Watchdog consumer listening", queue=QUEUE)
        async with queue.iterator() as it:
            async for message in it:
                await handle_message(message)


if __name__ == "__main__":
    asyncio.run(run_watchdog_consumer())
