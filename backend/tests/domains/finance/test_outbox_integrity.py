"""
Integration tests for the transactional-outbox projector's failure semantics.

The guarantee under test: if a broker publish fails mid-batch, the projector's
``session.begin()`` block rolls back so NO event is marked ``published = True``.
The events stay PENDING and are retried on the next poll cycle — at-least-once
delivery is preserved.
"""
from __future__ import annotations

import uuid

import pytest

import src.workers.outbox.projector as projector_mod
from src.domains.finance.models import OutboxEvent
from src.infrastructure.message_bus.rabbitmq_publisher import BrokerUnavailableError
from src.workers.outbox.projector import project_once
from tests.conftest import TestingSessionLocal


async def _insert_pending_event(routing_key: str) -> uuid.UUID:
    event = OutboxEvent(
        exchange="finguard.events",
        routing_key=routing_key,
        payload={"marker": uuid.uuid4().hex},
    )
    async with TestingSessionLocal() as session:
        session.add(event)
        await session.commit()
        return event.id


@pytest.mark.asyncio
async def test_projector_rolls_back_when_broker_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Point the projector at the test database and force every publish to fail.
    monkeypatch.setattr(projector_mod, "AsyncSessionLocal", TestingSessionLocal)

    async def _raise(**_: object) -> None:
        raise BrokerUnavailableError("broker down")

    monkeypatch.setattr(projector_mod, "publish", _raise)

    event_id = await _insert_pending_event("test.broker.down")

    with pytest.raises(BrokerUnavailableError):
        await project_once()

    # The event must remain unpublished after the rollback.
    async with TestingSessionLocal() as session:
        row = await session.get(OutboxEvent, event_id)
        assert row is not None
        assert row.published is False


@pytest.mark.asyncio
async def test_projector_marks_published_on_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(projector_mod, "AsyncSessionLocal", TestingSessionLocal)

    published: list[dict] = []

    async def _ok(**kwargs: object) -> None:
        published.append(dict(kwargs))

    monkeypatch.setattr(projector_mod, "publish", _ok)

    event_id = await _insert_pending_event("test.broker.ok")

    await project_once()

    async with TestingSessionLocal() as session:
        row = await session.get(OutboxEvent, event_id)
        assert row is not None
        assert row.published is True

    assert any(c.get("routing_key") == "test.broker.ok" for c in published)
