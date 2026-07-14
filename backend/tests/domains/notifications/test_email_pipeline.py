"""Phase 0 of the mailing system: the transactional email pipeline.

Covers the enqueue-side dedupe contract, template rendering, and the flush
worker's send / retry / dead-letter behaviour. Nothing here sends real mail —
``MAIL_ENABLED`` defaults to false, so the SMTP transport dry-runs.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domains.notifications.models import (
    EmailDeadLetter,
    EmailOutbox,
    EmailStatus,
)
from src.domains.notifications.service import NotificationService
from src.infrastructure.email.renderer import render
from src.workers.email import flusher
from tests.conftest import TestingSessionLocal


def _key() -> str:
    return f"test:{uuid.uuid4()}"


async def _clear_outbox() -> None:
    """Give the table-wide flush tests a clean slate — other tests commit
    email_outbox rows into the shared test DB, and the flush scans the whole
    table, so its counts would otherwise be non-deterministic."""
    async with TestingSessionLocal() as s:
        await s.execute(delete(EmailOutbox))
        await s.execute(delete(EmailDeadLetter))
        await s.commit()


# ── enqueue-side ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_enqueue_inserts_pending_row(db_session: AsyncSession) -> None:
    key = _key()
    ok = await NotificationService(db_session).enqueue_email(
        to_email="client@example.com",
        subject="Hello",
        template="_dev_smoke",
        context={"name": "Ada"},
        idempotency_key=key,
    )
    assert ok is True
    row = (
        await db_session.execute(
            select(EmailOutbox).where(EmailOutbox.idempotency_key == key)
        )
    ).scalar_one()
    assert row.status is EmailStatus.PENDING
    assert row.attempts == 0
    assert row.sent_at is None


@pytest.mark.asyncio
async def test_enqueue_is_idempotent(db_session: AsyncSession) -> None:
    key = _key()
    svc = NotificationService(db_session)
    first = await svc.enqueue_email(
        to_email="a@example.com", subject="s", template="_dev_smoke",
        context={}, idempotency_key=key,
    )
    second = await svc.enqueue_email(
        to_email="a@example.com", subject="s", template="_dev_smoke",
        context={}, idempotency_key=key,
    )
    assert first is True
    assert second is False  # same key → no-op, no second send
    count = (
        await db_session.execute(
            select(EmailOutbox).where(EmailOutbox.idempotency_key == key)
        )
    ).scalars().all()
    assert len(count) == 1


@pytest.mark.asyncio
async def test_enqueue_skips_when_no_recipient(db_session: AsyncSession) -> None:
    key = _key()
    ok = await NotificationService(db_session).enqueue_email(
        to_email=None, subject="s", template="_dev_smoke",
        context={}, idempotency_key=key,
    )
    assert ok is False
    rows = (
        await db_session.execute(
            select(EmailOutbox).where(EmailOutbox.idempotency_key == key)
        )
    ).scalars().all()
    assert rows == []


# ── rendering ─────────────────────────────────────────────────────────────────

def test_render_produces_html_and_text() -> None:
    html, text = render("_dev_smoke", {"name": "Grace"})
    assert "Grace" in html and "Grace" in text
    assert "<html" in html.lower()          # HTML part is a full document
    assert "<html" not in text.lower()      # text part is plain


def test_render_missing_template_raises() -> None:
    from jinja2 import TemplateNotFound

    with pytest.raises(TemplateNotFound):
        render("does_not_exist", {})


# ── flush worker ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_flush_marks_sent_in_dry_run(monkeypatch) -> None:
    # Pin the flag under test: a developer with MAIL_ENABLED=true in their .env
    # would otherwise make this attempt a real SMTP send and fail.
    monkeypatch.setattr(flusher.settings, "MAIL_ENABLED", False)
    await _clear_outbox()
    key = _key()
    async with TestingSessionLocal() as s:
        await NotificationService(s).enqueue_email(
            to_email="client@example.com", subject="Hi", template="_dev_smoke",
            context={"name": "X"}, idempotency_key=key,
        )
        await s.commit()

    result = await flusher.flush_once(session_factory=TestingSessionLocal)
    assert result["sent"] >= 1

    async with TestingSessionLocal() as s:
        row = (
            await s.execute(select(EmailOutbox).where(EmailOutbox.idempotency_key == key))
        ).scalar_one()
        assert row.status is EmailStatus.SENT
        assert row.sent_at is not None


@pytest.mark.asyncio
async def test_flush_dead_letters_after_exhausting_retries(monkeypatch) -> None:
    await _clear_outbox()
    key = _key()
    async with TestingSessionLocal() as s:
        await NotificationService(s).enqueue_email(
            to_email="client@example.com", subject="Hi", template="_dev_smoke",
            context={"name": "X"}, idempotency_key=key,
        )
        await s.commit()

    async def _boom(**_: object) -> None:
        raise RuntimeError("smtp exploded")

    monkeypatch.setattr(flusher, "send_email", _boom)
    monkeypatch.setattr(flusher.settings, "EMAIL_MAX_RETRIES", 1)

    result = await flusher.flush_once(session_factory=TestingSessionLocal)
    assert result["dead_lettered"] == 1

    async with TestingSessionLocal() as s:
        # Moved out of the outbox…
        assert (
            await s.execute(select(EmailOutbox).where(EmailOutbox.idempotency_key == key))
        ).scalar_one_or_none() is None
        # …and into the dead-letter table with the error preserved.
        dl = (
            await s.execute(
                select(EmailDeadLetter).where(EmailDeadLetter.idempotency_key == key)
            )
        ).scalar_one()
        assert dl.attempts == 1
        assert "smtp exploded" in (dl.last_error or "")
