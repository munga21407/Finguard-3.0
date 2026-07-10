"""Phase 1 mailing triggers on the identity domain.

Registration enqueues a welcome email; the admin verification transition
(is_verified false → true) enqueues an "account approved" email. Both are
idempotency-keyed and ride the account transaction. Nothing sends — MAIL_ENABLED
is false in tests.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domains.identity.schemas import UserCreate, UserUpdate
from src.domains.identity.service import IdentityService
from src.domains.notifications.models import EmailOutbox


async def _email_for(db: AsyncSession, key: str) -> EmailOutbox | None:
    return (
        await db.execute(select(EmailOutbox).where(EmailOutbox.idempotency_key == key))
    ).scalar_one_or_none()


def _new_user(email: str | None = None) -> UserCreate:
    return UserCreate(
        email=email or f"u-{uuid.uuid4().hex[:8]}@example.com",
        password="secure1234",
        full_name="Grace Hopper",
    )


@pytest.mark.asyncio
async def test_register_enqueues_welcome(db_session: AsyncSession) -> None:
    svc = IdentityService(db_session)
    user = await svc.register(_new_user())

    row = await _email_for(db_session, f"welcome:{user.id}")
    assert row is not None
    assert row.template == "welcome"
    assert row.to_email == user.email
    # The first account bootstraps a verified OWNER, so the welcome is the
    # "active" variant.
    assert row.context["is_verified"] is True


@pytest.mark.asyncio
async def test_second_registrant_gets_verification_email(db_session: AsyncSession) -> None:
    from sqlalchemy import select

    svc = IdentityService(db_session)
    await svc.register(_new_user())              # first → verified owner (welcome)
    second = await svc.register(_new_user())     # subsequent → must verify email

    # Non-bootstrap registrants get a verification email (not a welcome).
    assert await _email_for(db_session, f"welcome:{second.id}") is None
    row = (
        await db_session.execute(
            select(EmailOutbox).where(
                EmailOutbox.to_email == second.email,
                EmailOutbox.template == "verify_email",
            )
        )
    ).scalars().first()
    assert row is not None
    assert "verify_url" in row.context


@pytest.mark.asyncio
async def test_verification_transition_enqueues_approved(db_session: AsyncSession) -> None:
    svc = IdentityService(db_session)
    await svc.register(_new_user())              # burn the owner slot
    user = await svc.register(_new_user())       # unverified viewer
    assert user.is_verified is False

    await svc.update_user(user.id, UserUpdate(is_verified=True))

    row = await _email_for(db_session, f"approved:{user.id}")
    assert row is not None
    assert row.template == "account_approved"
    assert row.to_email == user.email


@pytest.mark.asyncio
async def test_non_verification_update_sends_no_email(db_session: AsyncSession) -> None:
    svc = IdentityService(db_session)
    await svc.register(_new_user())
    user = await svc.register(_new_user())

    # A profile edit that does not flip is_verified must not email.
    await svc.update_user(user.id, UserUpdate(full_name="Renamed"))

    assert await _email_for(db_session, f"approved:{user.id}") is None
