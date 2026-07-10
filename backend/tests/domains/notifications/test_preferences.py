"""Notification preferences: opt-out suppression, transactional override, and the
signed unsubscribe token.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import UnauthorizedError
from src.core.security import (
    create_access_token,
    create_unsubscribe_token,
    decode_unsubscribe_token,
)
from src.domains.notifications.models import EmailCategory, EmailOutbox
from src.domains.notifications.service import NotificationService


def _email() -> str:
    return f"pref-{uuid.uuid4().hex[:8]}@example.com"


def _key() -> str:
    return f"test:{uuid.uuid4()}"


# ── enqueue suppression ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_opted_out_suppressible_email_is_not_enqueued(db_session: AsyncSession) -> None:
    email = _email()
    svc = NotificationService(db_session)
    await svc.set_opt_out(email, EmailCategory.REMINDER, opted_out=True)

    ok = await svc.enqueue_email(
        to_email=email, subject="Reminder", template="payment_reminder",
        context={}, idempotency_key=_key(), category=EmailCategory.REMINDER,
    )
    assert ok is False


@pytest.mark.asyncio
async def test_transactional_email_ignores_opt_out(db_session: AsyncSession) -> None:
    email = _email()
    svc = NotificationService(db_session)
    # Even if a row somehow existed, a receipt is mandatory. set_opt_out refuses
    # to record a transactional category, so this is a double guarantee.
    await svc.set_opt_out(email, EmailCategory.RECEIPT, opted_out=True)

    key = _key()
    ok = await svc.enqueue_email(
        to_email=email, subject="Receipt", template="payment_receipt",
        context={}, idempotency_key=key, category=EmailCategory.RECEIPT,
    )
    assert ok is True
    row = (
        await db_session.execute(select(EmailOutbox).where(EmailOutbox.idempotency_key == key))
    ).scalar_one()
    assert row.to_email == email


@pytest.mark.asyncio
async def test_opt_in_re_enables(db_session: AsyncSession) -> None:
    email = _email()
    svc = NotificationService(db_session)
    await svc.set_opt_out(email, EmailCategory.APPROVAL, opted_out=True)
    assert EmailCategory.APPROVAL in await svc.list_opt_outs(email)

    await svc.set_opt_out(email, EmailCategory.APPROVAL, opted_out=False)
    assert await svc.list_opt_outs(email) == set()

    ok = await svc.enqueue_email(
        to_email=email, subject="Review", template="approval_needed",
        context={}, idempotency_key=_key(), category=EmailCategory.APPROVAL,
    )
    assert ok is True


@pytest.mark.asyncio
async def test_set_opt_out_ignores_transactional_category(db_session: AsyncSession) -> None:
    email = _email()
    svc = NotificationService(db_session)
    await svc.set_opt_out(email, EmailCategory.INVOICE, opted_out=True)
    assert await svc.list_opt_outs(email) == set()   # nothing recorded


# ── unsubscribe token ─────────────────────────────────────────────────────────

def test_unsubscribe_token_roundtrips() -> None:
    token = create_unsubscribe_token("Client@Example.com", "reminder")
    email, category = decode_unsubscribe_token(token)
    assert email == "client@example.com"   # normalised to lowercase
    assert category == "reminder"


def test_auth_token_is_rejected_as_unsubscribe() -> None:
    # A normal access token must not be usable as an unsubscribe token.
    access = create_access_token("some-user-id")
    with pytest.raises(UnauthorizedError):
        decode_unsubscribe_token(access)
