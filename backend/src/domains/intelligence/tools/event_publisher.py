"""
RabbitMQ event publisher tool.

Restricted to the intelligence domain's outbound exchange so agents cannot
flood arbitrary exchanges. Only available when the orchestrator runs in
'actions' mode.
"""
from __future__ import annotations

from typing import Any

from langchain_core.tools import tool

from src.infrastructure.message_bus.rabbitmq_publisher import publish

ALLOWED_EXCHANGES = frozenset({
    "finguard.finance",
    "finguard.intelligence",
    "finguard.system",
})


def make_event_publisher(mode: str) -> Any:
    @tool
    async def publish_event(exchange: str, routing_key: str, payload: dict[str, Any]) -> str:
        """Publish a domain event to RabbitMQ.

        Only available in 'actions' mode. Restricted to approved exchanges.

        Args:
            exchange: Target exchange name (must be in the allowed set).
            routing_key: Dot-separated routing key (e.g. "finance.watchdog.anomaly").
            payload: JSON-serialisable event body.
        """
        if mode != "actions":
            return "Event publishing is disabled in 'insights' mode."
        if exchange not in ALLOWED_EXCHANGES:
            return f"Exchange '{exchange}' is not permitted. Allowed: {sorted(ALLOWED_EXCHANGES)}"
        await publish(exchange, routing_key, payload)
        return f"Event published to {exchange}/{routing_key}"

    return publish_event
