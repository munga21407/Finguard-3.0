"""
Unit tests for the RabbitMQ publisher's broker-down behaviour.

The transactional-outbox guarantee depends entirely on ``publish()`` *raising*
(not silently skipping) when the broker connection is missing or closed.  If it
returned quietly, the projector would commit ``published = True`` for an event
the broker never received.
"""
from __future__ import annotations

import pytest

import src.infrastructure.message_bus.rabbitmq_publisher as pub
from src.infrastructure.message_bus.rabbitmq_publisher import (
    BrokerUnavailableError,
    publish,
)


@pytest.mark.asyncio
async def test_publish_raises_when_connection_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pub, "_connection", None)
    with pytest.raises(BrokerUnavailableError):
        await publish("finguard.events", "expenses.created", {"hello": "world"})


@pytest.mark.asyncio
async def test_publish_raises_when_connection_is_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    class _ClosedConn:
        is_closed = True

    monkeypatch.setattr(pub, "_connection", _ClosedConn())
    with pytest.raises(BrokerUnavailableError):
        await publish("finguard.events", "mpesa.reconciled", {"trans_id": "ABC123"})
