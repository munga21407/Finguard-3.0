"""Unit tests for the watchdog DLQ drain (``dlq.drain_watchdog_dlq``).

Exercises the three dispositions of ``_drain_dlq`` against fake aio-pika objects
(no real broker): a poison message past ``MAX_DEATH_COUNT`` is dropped, an
eligible message is replayed to the primary exchange, and a republish failure
leaves the message in the DLQ (nacked, requeued) — never silently lost.
"""
from __future__ import annotations

import json

import pytest

import src.workers.tasks.dlq_tasks as dlq
from src.workers.tasks.dlq_tasks import (
    _extract_death_reasons,
    _get_death_count,
)

# ── Fake aio-pika topology ────────────────────────────────────────────────────

class FakeMessage:
    def __init__(self, headers: dict, body: bytes) -> None:
        self.headers = headers
        self.body = body
        self.content_type = "application/json"
        self.acked = False
        self.nacked = False
        self.requeued: bool | None = None

    async def ack(self) -> None:
        self.acked = True

    async def nack(self, requeue: bool = False) -> None:
        self.nacked = True
        self.requeued = requeue


class FakeExchange:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.published: list[tuple[object, str]] = []

    async def publish(self, message: object, routing_key: str = "") -> None:
        if self.fail:
            raise RuntimeError("primary exchange unavailable")
        self.published.append((message, routing_key))


class FakeQueue:
    def __init__(self, messages: list[FakeMessage]) -> None:
        self._messages = list(messages)

    async def bind(self, exchange: object, routing_key: str = "") -> None:
        pass

    async def get(self, fail: bool = False) -> FakeMessage | None:
        return self._messages.pop(0) if self._messages else None


class FakeChannel:
    def __init__(self, queue: FakeQueue, primary: FakeExchange) -> None:
        self._queue = queue
        self._primary = primary

    async def set_qos(self, prefetch_count: int = 0) -> None:
        pass

    async def declare_exchange(self, name: str, type_: object = None, durable: bool = True):
        return self._primary if name == "finguard.events" else FakeExchange()

    async def declare_queue(self, name: str, durable: bool = True) -> FakeQueue:
        return self._queue


class FakeConnection:
    def __init__(self, channel: FakeChannel) -> None:
        self._channel = channel

    async def channel(self) -> FakeChannel:
        return self._channel

    async def __aenter__(self) -> FakeConnection:
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False


def _patch_broker(
    monkeypatch: pytest.MonkeyPatch,
    messages: list[FakeMessage],
    *,
    primary_fail: bool = False,
) -> FakeExchange:
    primary = FakeExchange(fail=primary_fail)
    channel = FakeChannel(FakeQueue(messages), primary)

    async def _connect_robust(*_a: object, **_k: object) -> FakeConnection:
        return FakeConnection(channel)

    monkeypatch.setattr(dlq.aio_pika, "connect_robust", _connect_robust)
    return primary


def _msg(death_count: int, expense_id: str = "exp-1") -> FakeMessage:
    headers = (
        {"x-death": [{"count": death_count, "queue": "q", "reason": "rejected"}]}
        if death_count
        else {}
    )
    body = json.dumps({"payload": {"expense_id": expense_id}}).encode()
    return FakeMessage(headers, body)


# ── Header helpers ────────────────────────────────────────────────────────────

def test_get_death_count_sums_entries() -> None:
    headers = {"x-death": [{"count": 2}, {"count": 3}]}
    assert _get_death_count(headers) == 5


def test_get_death_count_handles_missing_header() -> None:
    assert _get_death_count({}) == 0


def test_extract_death_reasons_shape() -> None:
    headers = {"x-death": [{"queue": "q", "reason": "expired", "count": 1}]}
    reasons = _extract_death_reasons(headers)
    assert reasons[0]["queue"] == "q" and reasons[0]["reason"] == "expired"


# ── Drain dispositions ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_poison_message_dropped_after_max_deaths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # death_count 4 > MAX_DEATH_COUNT (3) → dropped (acked, NOT republished).
    poison = _msg(death_count=dlq.MAX_DEATH_COUNT + 1)
    primary = _patch_broker(monkeypatch, [poison])

    stats = await dlq._drain_dlq(batch_size=10)

    assert stats == {"replayed": 0, "discarded": 1, "skipped": 0, "total": 1}
    assert poison.acked is True
    assert primary.published == []  # never replayed


@pytest.mark.asyncio
async def test_eligible_message_replayed(monkeypatch: pytest.MonkeyPatch) -> None:
    # death_count within the limit → republished to primary then acked.
    msg = _msg(death_count=1)
    primary = _patch_broker(monkeypatch, [msg])

    stats = await dlq._drain_dlq(batch_size=10)

    assert stats == {"replayed": 1, "discarded": 0, "skipped": 0, "total": 1}
    assert msg.acked is True
    assert len(primary.published) == 1
    assert primary.published[0][1] == dlq._PRIMARY_ROUTING_KEY


@pytest.mark.asyncio
async def test_republish_failure_requeues_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Primary publish raises → message left in DLQ (nacked, requeued), never lost.
    msg = _msg(death_count=1)
    _patch_broker(monkeypatch, [msg], primary_fail=True)

    stats = await dlq._drain_dlq(batch_size=10)

    assert stats == {"replayed": 0, "discarded": 0, "skipped": 1, "total": 1}
    assert msg.acked is False
    assert msg.nacked is True and msg.requeued is True


@pytest.mark.asyncio
async def test_message_exactly_at_threshold_is_replayed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # death_count == MAX_DEATH_COUNT is NOT poison (guard is strictly greater-than).
    msg = _msg(death_count=dlq.MAX_DEATH_COUNT)
    primary = _patch_broker(monkeypatch, [msg])

    stats = await dlq._drain_dlq(batch_size=10)

    assert stats["replayed"] == 1 and stats["discarded"] == 0
    assert len(primary.published) == 1
