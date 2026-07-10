"""
Registration / verification lifecycle and the /me + admin user-management flow.

  * First registration bootstraps a verified OWNER.
  * Subsequent self-registrations are unverified VIEWERs that cannot log in.
  * An admin (user:manage) can verify a pending user, who can then log in.
  * /me returns the authenticated user from the backend source of truth.
"""
from __future__ import annotations

import uuid
from collections.abc import Callable

import pytest
from httpx import AsyncClient

from src.domains.identity.models import User, UserRole


async def _register(client: AsyncClient, email: str) -> AsyncClient:
    return await client.post(
        "/api/v1/identity/register",
        json={"email": email, "password": "secure1234", "full_name": "Test User"},
    )


@pytest.mark.asyncio
async def test_first_user_is_verified_owner_and_can_login(client: AsyncClient) -> None:
    email = f"owner-{uuid.uuid4().hex[:8]}@finguard.io"
    res = await _register(client, email)
    assert res.status_code == 201
    body = res.json()
    assert body["role"] == "owner"
    assert body["is_verified"] is True

    login = await client.post(
        "/api/v1/identity/token", json={"email": email, "password": "secure1234"}
    )
    assert login.status_code == 200
    assert "access_token" in login.json()


@pytest.mark.asyncio
async def test_second_user_is_unverified_viewer_and_cannot_login(client: AsyncClient) -> None:
    await _register(client, f"first-{uuid.uuid4().hex[:8]}@finguard.io")

    email = f"second-{uuid.uuid4().hex[:8]}@finguard.io"
    res = await _register(client, email)
    assert res.status_code == 201
    body = res.json()
    assert body["role"] == "viewer"
    assert body["is_verified"] is False

    login = await client.post(
        "/api/v1/identity/token", json={"email": email, "password": "secure1234"}
    )
    assert login.status_code == 403  # pending verification


@pytest.mark.asyncio
async def test_admin_can_verify_pending_user_who_then_logs_in(
    client: AsyncClient, auth_as: Callable[..., User]
) -> None:
    from src.core.security import create_email_verification_token

    await _register(client, f"owner-{uuid.uuid4().hex[:8]}@finguard.io")
    email = f"pending-{uuid.uuid4().hex[:8]}@finguard.io"
    reg = await _register(client, email)
    user_id = reg.json()["id"]

    # Gate 1: the user confirms their email (self-service).
    verify = await client.post(
        "/api/v1/identity/verify-email",
        json={"token": create_email_verification_token(user_id)},
    )
    assert verify.status_code == 204

    # Gate 2: an admin approves the account.
    auth_as(UserRole.OWNER)
    patch = await client.patch(
        f"/api/v1/identity/users/{user_id}",
        json={"is_verified": True, "role": "accountant"},
    )
    assert patch.status_code == 200
    assert patch.json()["is_verified"] is True
    assert patch.json()["role"] == "accountant"

    # Both gates satisfied → login succeeds.
    login = await client.post(
        "/api/v1/identity/token", json={"email": email, "password": "secure1234"}
    )
    assert login.status_code == 200


@pytest.mark.asyncio
async def test_me_returns_authenticated_user(
    client: AsyncClient, auth_as: Callable[..., User]
) -> None:
    user = auth_as(UserRole.MANAGER)
    res = await client.get("/api/v1/identity/me")
    assert res.status_code == 200
    body = res.json()
    assert body["id"] == str(user.id)
    assert body["role"] == "manager"
