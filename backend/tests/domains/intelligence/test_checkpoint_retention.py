"""Checkpoint-retention sweep (workers.tasks.batch.enforce_checkpoint_retention).

The LangGraph checkpointer tables (``checkpoints``/``checkpoint_blobs``/
``checkpoint_writes``, migration ``0025``) are raw-SQL tables, not SQLAlchemy
ORM models — ``tests/conftest.py``'s ``Base.metadata.create_all`` never
creates them, so this file creates them itself (schema mirrors migration
0025 exactly) rather than relying on the shared fixture.

No ``created_at`` column exists on these tables; retention keys off the
``checkpoint`` JSONB payload's required ``ts`` field instead — these tests
pin that behavior directly with hand-seeded rows.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.metrics import CHECKPOINT_RETENTION_DELETED_THREADS
from src.workers.tasks import batch
from tests.conftest import TestingSessionLocal, engine


def _sample_deleted_threads() -> float:
    return CHECKPOINT_RETENTION_DELETED_THREADS._value.get()


@pytest_asyncio.fixture
async def _checkpoint_tables(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[None]:
    # batch.py's retention functions open the *application*'s AsyncSessionLocal
    # internally (no session parameter, matching _run_data_retention_async's
    # existing shape) — which is bound to settings.DATABASE_URL, a different
    # database than TestingSessionLocal's derived "finguard_test" DB. Point it
    # at the same engine this fixture seeds, or the job would query an empty
    # (or table-less) database and every assertion below would be vacuous.
    monkeypatch.setattr(batch, "AsyncSessionLocal", TestingSessionLocal)

    async with engine.begin() as conn:
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS checkpoints (
                thread_id TEXT NOT NULL,
                checkpoint_ns TEXT NOT NULL DEFAULT '',
                checkpoint_id TEXT NOT NULL,
                parent_checkpoint_id TEXT,
                type TEXT,
                checkpoint JSONB NOT NULL,
                metadata JSONB NOT NULL DEFAULT '{}',
                PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id)
            )
        """))
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS checkpoint_blobs (
                thread_id TEXT NOT NULL,
                checkpoint_ns TEXT NOT NULL DEFAULT '',
                channel TEXT NOT NULL,
                version TEXT NOT NULL,
                type TEXT NOT NULL,
                blob BYTEA,
                PRIMARY KEY (thread_id, checkpoint_ns, channel, version)
            )
        """))
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS checkpoint_writes (
                thread_id TEXT NOT NULL,
                checkpoint_ns TEXT NOT NULL DEFAULT '',
                checkpoint_id TEXT NOT NULL,
                task_id TEXT NOT NULL,
                idx INTEGER NOT NULL,
                channel TEXT NOT NULL,
                type TEXT,
                blob BYTEA NOT NULL,
                task_path TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id, task_id, idx)
            )
        """))
    yield
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE checkpoint_writes, checkpoint_blobs, checkpoints"))


async def _seed_checkpoint(
    session: AsyncSession, *, thread_id: str, checkpoint_id: str, ts: datetime
) -> None:
    await session.execute(
        text("""
            INSERT INTO checkpoints (thread_id, checkpoint_id, type, checkpoint, metadata)
            VALUES (:thread_id, :checkpoint_id, 'test', :checkpoint, '{}')
            ON CONFLICT (thread_id, checkpoint_ns, checkpoint_id) DO NOTHING
        """),
        {
            "thread_id": thread_id,
            "checkpoint_id": checkpoint_id,
            "checkpoint": f'{{"v": 1, "id": "{checkpoint_id}", "ts": "{ts.isoformat()}", '
            f'"channel_values": {{}}, "channel_versions": {{}}, "versions_seen": {{}}}}',
        },
    )
    await session.execute(
        text("""
            INSERT INTO checkpoint_blobs (thread_id, channel, version, type, blob)
            VALUES (:thread_id, 'messages', :checkpoint_id, 'json', '{}'::bytea)
            ON CONFLICT (thread_id, checkpoint_ns, channel, version) DO NOTHING
        """),
        {"thread_id": thread_id, "checkpoint_id": checkpoint_id},
    )
    await session.execute(
        text("""
            INSERT INTO checkpoint_writes
                (thread_id, checkpoint_id, task_id, idx, channel, blob)
            VALUES (:thread_id, :checkpoint_id, 'task-1', 0, 'messages', '{}'::bytea)
            ON CONFLICT (thread_id, checkpoint_ns, checkpoint_id, task_id, idx) DO NOTHING
        """),
        {"thread_id": thread_id, "checkpoint_id": checkpoint_id},
    )


async def _thread_row_counts(session: AsyncSession, thread_id: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for table in ("checkpoints", "checkpoint_blobs", "checkpoint_writes"):
        result = await session.execute(
            text(f"SELECT COUNT(*) FROM {table} WHERE thread_id = :tid"),  # noqa: S608
            {"tid": thread_id},
        )
        counts[table] = result.scalar_one()
    return counts


@pytest.mark.asyncio
async def test_old_thread_purged_recent_thread_kept(
    _checkpoint_tables: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(batch.settings, "CHECKPOINT_RETENTION_DAYS", 30)
    now = datetime.now(UTC)

    async with TestingSessionLocal() as session:
        # Old thread: most recent checkpoint is 40 days ago — eligible.
        await _seed_checkpoint(
            session, thread_id="old-thread", checkpoint_id="ckpt-old-1",
            ts=now - timedelta(days=45),
        )
        await _seed_checkpoint(
            session, thread_id="old-thread", checkpoint_id="ckpt-old-2",
            ts=now - timedelta(days=40),
        )
        # Recent thread: most recent checkpoint is 1 day ago — must survive.
        await _seed_checkpoint(
            session, thread_id="recent-thread", checkpoint_id="ckpt-recent-1",
            ts=now - timedelta(days=1),
        )
        await session.commit()

    before = _sample_deleted_threads()
    result = await batch._run_checkpoint_retention_async()
    assert result == {"status": "ok", "deleted_threads": 1}
    assert _sample_deleted_threads() == before + 1

    async with TestingSessionLocal() as session:
        assert await _thread_row_counts(session, "old-thread") == {
            "checkpoints": 0, "checkpoint_blobs": 0, "checkpoint_writes": 0,
        }
        assert await _thread_row_counts(session, "recent-thread") == {
            "checkpoints": 1, "checkpoint_blobs": 1, "checkpoint_writes": 1,
        }


@pytest.mark.asyncio
async def test_thread_with_any_recent_checkpoint_is_kept_entirely(
    _checkpoint_tables: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Retention keys off the MOST RECENT checkpoint per thread — a thread
    with one very old checkpoint but a recent one too must not be purged
    (that would corrupt its replay chain)."""
    monkeypatch.setattr(batch.settings, "CHECKPOINT_RETENTION_DAYS", 30)
    now = datetime.now(UTC)

    async with TestingSessionLocal() as session:
        await _seed_checkpoint(
            session, thread_id="mixed-thread", checkpoint_id="ckpt-1",
            ts=now - timedelta(days=90),
        )
        await _seed_checkpoint(
            session, thread_id="mixed-thread", checkpoint_id="ckpt-2",
            ts=now - timedelta(days=2),
        )
        await session.commit()

    result = await batch._run_checkpoint_retention_async()
    assert result == {"status": "no_work", "deleted_threads": 0}

    async with TestingSessionLocal() as session:
        counts = await _thread_row_counts(session, "mixed-thread")
        assert counts["checkpoints"] == 2


@pytest.mark.asyncio
async def test_no_eligible_threads_is_no_work(_checkpoint_tables: None) -> None:
    result = await batch._run_checkpoint_retention_async()
    assert result == {"status": "no_work", "deleted_threads": 0}
