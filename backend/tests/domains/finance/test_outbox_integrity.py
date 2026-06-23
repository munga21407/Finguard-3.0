"""
Integration tests for the transactional-outbox projector's failure semantics.

The guarantees under test:
  * Per-event isolation — a broker failure on one event increments its
    ``retry_count`` (it stays PENDING) WITHOUT rolling back the events that
    already published in the same batch.
  * Dead-lettering — once an event's ``retry_count`` reaches
    ``OUTBOX_MAX_RETRIES`` it is moved into ``outbox_dead_letters`` and removed
    from the pipeline, so a poison message can never block the projector.
At-least-once delivery is preserved: a still-PENDING event is retried next poll.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

import src.workers.outbox.projector as projector_mod
from src.core.config import settings
from src.domains.finance.models import OutboxDeadLetter, OutboxEvent
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
async def test_broker_failure_increments_retry_without_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A single failing publish must be isolated: project_once does NOT raise, and
    # the event stays PENDING with retry_count bumped.
    monkeypatch.setattr(projector_mod, "AsyncSessionLocal", TestingSessionLocal)

    async def _raise(**_: object) -> None:
        raise BrokerUnavailableError("broker down")

    monkeypatch.setattr(projector_mod, "publish", _raise)

    event_id = await _insert_pending_event("test.broker.down")

    published = await project_once()  # must not raise
    assert published == 0

    async with TestingSessionLocal() as session:
        row = await session.get(OutboxEvent, event_id)
        assert row is not None
        assert row.published is False
        assert row.retry_count == 1
        assert row.last_error is not None


@pytest.mark.asyncio
async def test_poison_event_does_not_block_healthy_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # One event's broker failure must not roll back a healthy batch-mate.
    monkeypatch.setattr(projector_mod, "AsyncSessionLocal", TestingSessionLocal)

    async def _selective(**kwargs: object) -> None:
        if kwargs.get("routing_key") == "test.poison":
            raise BrokerUnavailableError("poison")

    monkeypatch.setattr(projector_mod, "publish", _selective)

    poison_id = await _insert_pending_event("test.poison")
    healthy_id = await _insert_pending_event("test.healthy")

    await project_once()

    async with TestingSessionLocal() as session:
        poison = await session.get(OutboxEvent, poison_id)
        healthy = await session.get(OutboxEvent, healthy_id)
        assert poison is not None and poison.published is False and poison.retry_count == 1
        assert healthy is not None and healthy.published is True


@pytest.mark.asyncio
async def test_event_dead_letters_after_max_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(projector_mod, "AsyncSessionLocal", TestingSessionLocal)

    async def _raise(**_: object) -> None:
        raise BrokerUnavailableError("broker down")

    monkeypatch.setattr(projector_mod, "publish", _raise)

    event_id = await _insert_pending_event("test.dead.letter")

    # Each poll cycle is one failed attempt; the Nth (= OUTBOX_MAX_RETRIES) moves it.
    for _ in range(settings.OUTBOX_MAX_RETRIES):
        await project_once()

    async with TestingSessionLocal() as session:
        # The source row is gone from the pipeline …
        assert await session.get(OutboxEvent, event_id) is None
        # … and a dead-letter row preserves it for inspection.
        dl = (
            await session.execute(
                select(OutboxDeadLetter).where(
                    OutboxDeadLetter.original_event_id == event_id
                )
            )
        ).scalar_one()
        assert dl.retry_count == settings.OUTBOX_MAX_RETRIES
        assert dl.routing_key == "test.dead.letter"
        assert dl.last_error is not None


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
