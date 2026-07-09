"""Email delivery admin (inspect / replay / resend), deliverability headers, and
the operator RBAC gate.
"""
from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.domains.identity.models import User, UserRole
from src.domains.notifications.models import (
    EmailDeadLetter,
    EmailOutbox,
    EmailStatus,
)
from src.domains.notifications.service import NotificationService
from src.infrastructure.email.smtp import _build_message


def _key() -> str:
    return f"admin:{uuid.uuid4()}"


# ── Deliverability headers ────────────────────────────────────────────────────

def test_suppressible_email_carries_list_unsubscribe() -> None:
    msg = _build_message(
        to_email="c@example.com", to_name="C", subject="Reminder",
        html="<p>hi</p>", text="hi",
        unsubscribe_url="https://app/api/v1/notifications/unsubscribe?token=abc",
    )
    assert msg["List-Unsubscribe"] == "<https://app/api/v1/notifications/unsubscribe?token=abc>"
    assert msg["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
    assert msg["Reply-To"]
    assert msg["Message-ID"]


def test_transactional_email_has_no_list_unsubscribe() -> None:
    msg = _build_message(
        to_email="c@example.com", to_name=None, subject="Receipt",
        html="<p>hi</p>", text="hi",
    )
    assert msg["List-Unsubscribe"] is None


# ── Admin service ─────────────────────────────────────────────────────────────

async def _seed_outbox(db: AsyncSession, status: EmailStatus) -> EmailOutbox:
    row = EmailOutbox(
        to_email="seed@example.com", subject="s", template="_dev_smoke",
        context={"name": "x"}, status=status, idempotency_key=_key(),
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


@pytest.mark.asyncio
async def test_kpis_counts_by_status(db_session: AsyncSession) -> None:
    await _seed_outbox(db_session, EmailStatus.PENDING)
    await _seed_outbox(db_session, EmailStatus.SENT)
    kpis = await NotificationService(db_session).kpis()
    assert kpis["pending"] >= 1
    assert kpis["sent"] >= 1
    assert set(kpis) == {"pending", "sent", "failed", "dead_lettered"}


@pytest.mark.asyncio
async def test_list_outbox_filters_by_status(db_session: AsyncSession) -> None:
    failed = await _seed_outbox(db_session, EmailStatus.FAILED)
    items, total = await NotificationService(db_session).list_outbox(
        status=EmailStatus.FAILED
    )
    assert total >= 1
    assert failed.id in {i.id for i in items}
    assert all(i.status is EmailStatus.FAILED for i in items)


@pytest.mark.asyncio
async def test_replay_dead_letter_requeues_and_removes(db_session: AsyncSession) -> None:
    dl = EmailDeadLetter(
        original_email_id=uuid.uuid4(),
        to_email="dl@example.com", subject="s", template="_dev_smoke",
        context={"name": "x"}, attempts=5, last_error="boom",
        idempotency_key=_key(), original_created_at=datetime.now(UTC),
    )
    db_session.add(dl)
    await db_session.commit()

    row = await NotificationService(db_session).replay_dead_letter(dl.id)
    assert row.status is EmailStatus.PENDING
    assert row.attempts == 0
    # Dead-letter is gone; a fresh pending outbox row exists.
    assert await db_session.get(EmailDeadLetter, dl.id) is None
    assert ":replay:" in row.idempotency_key


@pytest.mark.asyncio
async def test_resend_creates_fresh_pending_row(db_session: AsyncSession) -> None:
    sent = await _seed_outbox(db_session, EmailStatus.SENT)
    row = await NotificationService(db_session).resend(sent.id)
    assert row.id != sent.id
    assert row.status is EmailStatus.PENDING
    assert ":resend:" in row.idempotency_key
    assert row.template == sent.template


# ── RBAC gate ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_admin_email_endpoints_require_user_manage(
    client: AsyncClient, auth_as: Callable[..., User]
) -> None:
    auth_as(UserRole.ACCOUNTANT)
    denied = await client.get("/api/v1/notifications/admin/email/kpis")
    assert denied.status_code == 403

    auth_as(UserRole.OWNER)
    ok = await client.get("/api/v1/notifications/admin/email/kpis")
    assert ok.status_code == 200
    assert set(ok.json()) == {"pending", "sent", "failed", "dead_lettered"}
