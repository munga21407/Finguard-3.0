"""Self-service email verification — the second login gate (alongside admin
approval). Covers token validity, idempotency, resend, and the two-gate login
ordering.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import ForbiddenError, UnauthorizedError
from src.core.security import create_email_verification_token
from src.domains.identity.models import User
from src.domains.identity.schemas import UserCreate, UserUpdate
from src.domains.identity.service import IdentityService
from src.domains.notifications.models import EmailOutbox


def _u(email: str | None = None) -> UserCreate:
    return UserCreate(
        email=email or f"u-{uuid.uuid4().hex[:8]}@example.com",
        password="secure1234",
        full_name="Pat",
    )


async def _second_user(svc: IdentityService) -> User:
    """A non-bootstrap registrant: unverified email, pending admin approval."""
    await svc.register(_u())        # burn the owner slot
    return await svc.register(_u())


@pytest.mark.asyncio
async def test_bootstrap_owner_email_is_auto_verified(db_session: AsyncSession) -> None:
    owner = await IdentityService(db_session).register(_u())
    assert owner.email_verified_at is not None


@pytest.mark.asyncio
async def test_second_registrant_email_starts_unverified(db_session: AsyncSession) -> None:
    user = await _second_user(IdentityService(db_session))
    assert user.email_verified_at is None


@pytest.mark.asyncio
async def test_verify_email_sets_timestamp(db_session: AsyncSession) -> None:
    svc = IdentityService(db_session)
    user = await _second_user(svc)
    await svc.verify_email(create_email_verification_token(str(user.id)))

    refreshed = await db_session.get(User, user.id)
    assert refreshed is not None
    assert refreshed.email_verified_at is not None


@pytest.mark.asyncio
async def test_verify_email_is_idempotent(db_session: AsyncSession) -> None:
    svc = IdentityService(db_session)
    user = await _second_user(svc)
    token = create_email_verification_token(str(user.id))
    await svc.verify_email(token)
    await svc.verify_email(token)  # second time: no error


@pytest.mark.asyncio
async def test_verify_email_rejects_garbage(db_session: AsyncSession) -> None:
    with pytest.raises(UnauthorizedError):
        await IdentityService(db_session).verify_email("nonsense")


@pytest.mark.asyncio
async def test_resend_verification_for_unverified_enqueues(db_session: AsyncSession) -> None:
    svc = IdentityService(db_session)
    user = await _second_user(svc)
    await svc.resend_verification(user.email)

    rows = (
        await db_session.execute(
            select(EmailOutbox).where(
                EmailOutbox.to_email == user.email,
                EmailOutbox.template == "verify_email",
            )
        )
    ).scalars().all()
    assert len(rows) >= 1


@pytest.mark.asyncio
async def test_resend_is_noop_once_verified(db_session: AsyncSession) -> None:
    svc = IdentityService(db_session)
    user = await _second_user(svc)
    await svc.verify_email(create_email_verification_token(str(user.id)))

    # Count verify emails before/after a resend attempt — should not grow.
    before = len(
        (
            await db_session.execute(
                select(EmailOutbox).where(
                    EmailOutbox.to_email == user.email,
                    EmailOutbox.template == "verify_email",
                )
            )
        ).scalars().all()
    )
    await svc.resend_verification(user.email)
    after = len(
        (
            await db_session.execute(
                select(EmailOutbox).where(
                    EmailOutbox.to_email == user.email,
                    EmailOutbox.template == "verify_email",
                )
            )
        ).scalars().all()
    )
    assert after == before


@pytest.mark.asyncio
async def test_login_gates_are_ordered_email_then_admin(db_session: AsyncSession) -> None:
    svc = IdentityService(db_session)
    user = await _second_user(svc)

    # Gate 1 — email unverified: blocked, message points at the inbox.
    with pytest.raises(ForbiddenError, match="verify your email"):
        await svc.login(user.email, "secure1234")

    await svc.verify_email(create_email_verification_token(str(user.id)))

    # Gate 2 — email verified but admin hasn't approved: still blocked.
    with pytest.raises(ForbiddenError, match="administrator"):
        await svc.login(user.email, "secure1234")

    # Both gates cleared → login succeeds.
    await svc.update_user(user.id, UserUpdate(is_verified=True))
    result = await svc.login(user.email, "secure1234")
    assert result.access_token
