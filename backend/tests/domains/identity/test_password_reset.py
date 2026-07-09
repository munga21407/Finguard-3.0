"""Forgot-password / reset flow: email dispatch, token validity, one-time use,
session invalidation, and no account enumeration.
"""
from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import UnauthorizedError
from src.core.security import (
    create_password_reset_token,
    token_issued_after_password_change,
    verify_password,
)
from src.domains.identity.models import User
from src.domains.identity.schemas import UserCreate
from src.domains.identity.service import IdentityService
from src.domains.notifications.models import EmailOutbox


def _new_user(email: str | None = None) -> UserCreate:
    return UserCreate(
        email=email or f"u-{uuid.uuid4().hex[:8]}@example.com",
        password="original-pw-123",
        full_name="Ada Lovelace",
    )


# ── issued-after-change logic ─────────────────────────────────────────────────

def test_token_validity_vs_password_change() -> None:
    now = datetime(2026, 7, 9, 12, 0, tzinfo=UTC)
    before = int((now - timedelta(minutes=5)).timestamp())
    after = int((now + timedelta(minutes=5)).timestamp())
    assert token_issued_after_password_change(after, now) is True
    assert token_issued_after_password_change(before, now) is False   # stale token
    assert token_issued_after_password_change(None, now) is True       # legacy, no iat
    assert token_issued_after_password_change(before, None) is True    # never reset


# ── request side ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_request_reset_enqueues_email_for_known_user(db_session: AsyncSession) -> None:
    svc = IdentityService(db_session)
    user = await svc.register(_new_user())
    await svc.request_password_reset(user.email)

    row = (
        await db_session.execute(
            select(EmailOutbox).where(
                EmailOutbox.to_email == user.email,
                EmailOutbox.template == "password_reset",
            )
        )
    ).scalars().first()
    assert row is not None
    assert "reset_url" in row.context


@pytest.mark.asyncio
async def test_request_reset_is_silent_for_unknown_email(db_session: AsyncSession) -> None:
    svc = IdentityService(db_session)
    # No exception, no mail — and no signal about whether the address exists.
    await svc.request_password_reset("nobody@example.com")
    rows = (
        await db_session.execute(
            select(EmailOutbox).where(EmailOutbox.to_email == "nobody@example.com")
        )
    ).scalars().all()
    assert rows == []


# ── reset side ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_reset_changes_password_and_stamps_change_time(db_session: AsyncSession) -> None:
    svc = IdentityService(db_session)
    user = await svc.register(_new_user())
    token = create_password_reset_token(str(user.id))

    await svc.reset_password(token, "brand-new-pw-456")

    refreshed = await db_session.get(User, user.id)
    assert refreshed is not None
    assert verify_password("brand-new-pw-456", refreshed.hashed_password)
    assert not verify_password("original-pw-123", refreshed.hashed_password)
    assert refreshed.password_changed_at is not None


@pytest.mark.asyncio
async def test_reset_link_is_one_time_use(db_session: AsyncSession) -> None:
    svc = IdentityService(db_session)
    user = await svc.register(_new_user())
    token = create_password_reset_token(str(user.id))

    await svc.reset_password(token, "first-reset-pw-1")
    with pytest.raises(UnauthorizedError):
        await svc.reset_password(token, "second-reset-pw-2")


@pytest.mark.asyncio
async def test_reset_rejects_garbage_token(db_session: AsyncSession) -> None:
    with pytest.raises(UnauthorizedError):
        await IdentityService(db_session).reset_password("not-a-token", "whatever-123")


# ── HTTP surface ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_forgot_password_endpoint_always_202(client: AsyncClient) -> None:
    res = await client.post(
        "/api/v1/identity/forgot-password", json={"email": "ghost@example.com"}
    )
    assert res.status_code == 202  # same response whether or not the account exists


@pytest.mark.asyncio
async def test_reset_then_login_with_new_password(
    client: AsyncClient, db_session: AsyncSession, auth_as: Callable[..., User]
) -> None:
    # Register a verified user, then reset and confirm login uses the new password.
    svc = IdentityService(db_session)
    user = await svc.register(_new_user())   # first account → verified owner
    token = create_password_reset_token(str(user.id))

    res = await client.post(
        "/api/v1/identity/reset-password",
        json={"token": token, "new_password": "https-strong-pw-9"},
    )
    assert res.status_code == 204

    ok = await client.post(
        "/api/v1/identity/token",
        json={"email": user.email, "password": "https-strong-pw-9"},
    )
    assert ok.status_code == 200
    bad = await client.post(
        "/api/v1/identity/token",
        json={"email": user.email, "password": "original-pw-123"},
    )
    assert bad.status_code == 401
