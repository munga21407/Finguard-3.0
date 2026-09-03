"""
RabbitMQ event publisher tool.

Restricted to the intelligence domain's outbound exchange so agents cannot
flood arbitrary exchanges. Only available when the orchestrator runs in
'actions' mode.
"""
from __future__ import annotations

from typing import Any

from langchain_core.tools import tool

from src.domains.intelligence.agent_registry import allowed_event_exchanges
from src.infrastructure.message_bus.rabbitmq_publisher import (
    BrokerUnavailableError,
    publish,
)

ALLOWED_EXCHANGES = frozenset({
    "finguard.events",         # primary domain event bus (finance.transactions.classified, etc.)
    "finguard.finance",
    "finguard.intelligence",
    "finguard.system",
})


def make_event_publisher(mode: str, agent_id: str) -> Any:
    @tool
    async def publish_event(exchange: str, routing_key: str, payload: dict[str, Any]) -> str:
        """Publish a domain event to RabbitMQ.

        Only available in 'actions' mode. Restricted to approved exchanges,
        further narrowed to ``agent_id``'s own grant
        (``agent_registry.allowed_event_exchanges``).

        Args:
            exchange: Target exchange name (must be in the allowed set).
            routing_key: Dot-separated routing key (e.g. "finance.watchdog.anomaly").
            payload: JSON-serialisable event body.
        """
        if mode != "actions":
            return "Event publishing is disabled in 'insights' mode."
        agent_allowed = allowed_event_exchanges(agent_id)
        if exchange not in ALLOWED_EXCHANGES or exchange not in agent_allowed:
            permitted = ALLOWED_EXCHANGES & agent_allowed
            return (
                f"Exchange '{exchange}' is not permitted for agent '{agent_id}'. "
                f"Allowed: {sorted(permitted)}"
            )
        try:
            await publish(exchange, routing_key, payload)
        except BrokerUnavailableError:
            # Degrade gracefully rather than crashing the LangGraph node — the
            # broker is down, but the agent run should still complete.
            return (
                f"Event publish to {exchange}/{routing_key} deferred: "
                "message broker is temporarily unavailable."
            )
        return f"Event published to {exchange}/{routing_key}"

    return publish_event
