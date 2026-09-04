"""B's Celery classification persist now mints+validates a task-scoped VC
*inside the worker invocation itself*, right before the persist — not at
node-dispatch time (P2 of "Task-scoped VC end-to-end", see
docs/AGENTS_REMEDIATION_SPRINTS.md). Minting at dispatch would sit through an
unbounded queue delay and could easily outlive the VC's 5-minute TTL before
this code ever ran — this file's whole point is proving the fix actually
eliminates that race by construction (mint happens here, in this function).

``_run_batch_classification`` uses the *application's* ``AsyncSessionLocal``
(not a parameter), so it's repointed at ``TestingSessionLocal`` — the same fix
``test_checkpoint_retention.py`` needed for the same reason (two different
test databases otherwise). The model call, event publish, and Mongo hub write
are all mocked — hermetic, matching this codebase's Celery-task test
conventions.
"""
from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from src.domains.finance.models import LedgerEntry, TransactionType
from src.domains.intelligence.schemas import TransactionClassification
from src.workers.tasks import batch
from tests.conftest import TestingSessionLocal


@pytest.fixture(autouse=True)
def _use_testing_session(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(batch, "AsyncSessionLocal", TestingSessionLocal)
    monkeypatch.setattr(batch, "init_mongo", AsyncMock())
    monkeypatch.setattr(batch, "_publish_classified_event", AsyncMock())
    monkeypatch.setattr(batch, "_write_to_hub", AsyncMock(return_value="hub-artifact-1"))


async def _seed_unclassified_entry() -> uuid.UUID:
    async with TestingSessionLocal() as session:
        entry = LedgerEntry(
            account_id=uuid.uuid4(),
            transaction_type=TransactionType.DEBIT,
            amount=Decimal("42.00"),
            description="Test narrative",
            category=None,
        )
        session.add(entry)
        await session.commit()
        return entry.id


def _fake_classify(entry_id: uuid.UUID) -> AsyncMock:
    async def _classify(entries: list[dict[str, Any]]) -> list[TransactionClassification]:
        return [
            TransactionClassification(
                entry_id=str(entry_id), category="office_supplies", confidence=0.9
            )
        ]
    return AsyncMock(side_effect=_classify)


@pytest.mark.asyncio
async def test_batch_persists_when_task_vc_check_passes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry_id = await _seed_unclassified_entry()
    monkeypatch.setattr(batch, "_classify_batch_async", _fake_classify(entry_id))

    calls: list[dict[str, Any]] = []

    async def fake_require(**kwargs: Any) -> None:
        calls.append(kwargs)
    monkeypatch.setattr(batch, "require_task_vc", fake_require)

    result = await batch._run_batch_classification()

    assert result["status"] == "ok"
    assert result["classified"] == 1
    assert len(calls) == 1
    assert calls[0]["agent_id"] == "B"
    assert calls[0]["operation"] == "classify.batch_persist"
    uuid.UUID(calls[0]["transaction_id"])  # a fresh batch id, not an entry id

    async with TestingSessionLocal() as session:
        row = (
            await session.execute(select(LedgerEntry).where(LedgerEntry.id == entry_id))
        ).scalar_one()
        assert row.category == "office_supplies"

    batch._publish_classified_event.assert_awaited_once()  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_batch_not_persisted_when_task_vc_check_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry_id = await _seed_unclassified_entry()
    monkeypatch.setattr(batch, "_classify_batch_async", _fake_classify(entry_id))

    async def failing_require(**_kwargs: Any) -> None:
        raise RuntimeError("VC check failed (test)")
    monkeypatch.setattr(batch, "require_task_vc", failing_require)

    result = await batch._run_batch_classification()

    assert result["status"] == "vc_failed"
    assert result["classified"] == 0

    async with TestingSessionLocal() as session:
        row = (
            await session.execute(select(LedgerEntry).where(LedgerEntry.id == entry_id))
        ).scalar_one()
        assert row.category is None  # never persisted

    batch._publish_classified_event.assert_not_awaited()  # type: ignore[attr-defined]
    batch._write_to_hub.assert_not_awaited()  # type: ignore[attr-defined]
