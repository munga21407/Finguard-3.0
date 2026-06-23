"""
Secure first-user bootstrap via INITIAL_BOOTSTRAP_KEY.

When the key is configured (always the case in production), claiming the OWNER
role on the first account requires presenting the matching key — closing the
"first to register owns the system" hijack. A wrong key is rejected, and the key
is powerless once the owner already exists.
"""
from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from src.core.config import settings

_KEY = "test-bootstrap-key-" + "z" * 20


@pytest.fixture(autouse=True)
def _configure_bootstrap_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "INITIAL_BOOTSTRAP_KEY", _KEY)


def _payload(email: str, *, bootstrap_key: str | None = None) -> dict:
    body = {"email": email, "password": "secure1234", "full_name": "Boot User"}
    if bootstrap_key is not None:
        body["bootstrap_key"] = bootstrap_key
    return body


@pytest.mark.asyncio
async def test_first_user_with_correct_key_becomes_verified_owner(client: AsyncClient) -> None:
    email = f"owner-{uuid.uuid4().hex[:8]}@finguard.io"
    res = await client.post("/api/v1/identity/register", json=_payload(email, bootstrap_key=_KEY))
    assert res.status_code == 201
    body = res.json()
    assert body["role"] == "owner"
    assert body["is_verified"] is True

    login = await client.post(
        "/api/v1/identity/token", json={"email": email, "password": "secure1234"}
    )
    assert login.status_code == 200


@pytest.mark.asyncio
async def test_first_user_without_key_is_unverified_viewer(client: AsyncClient) -> None:
    email = f"nokey-{uuid.uuid4().hex[:8]}@finguard.io"
    res = await client.post("/api/v1/identity/register", json=_payload(email))
    assert res.status_code == 201
    body = res.json()
    assert body["role"] == "viewer"
    assert body["is_verified"] is False

    login = await client.post(
        "/api/v1/identity/token", json={"email": email, "password": "secure1234"}
    )
    assert login.status_code == 403  # pending verification


@pytest.mark.asyncio
async def test_first_user_with_wrong_key_is_rejected(client: AsyncClient) -> None:
    email = f"wrong-{uuid.uuid4().hex[:8]}@finguard.io"
    res = await client.post(
        "/api/v1/identity/register", json=_payload(email, bootstrap_key="not-the-key")
    )
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_key_is_powerless_once_owner_claimed(client: AsyncClient) -> None:
    # First account claims OWNER with the key.
    first = f"first-{uuid.uuid4().hex[:8]}@finguard.io"
    res = await client.post("/api/v1/identity/register", json=_payload(first, bootstrap_key=_KEY))
    assert res.status_code == 201

    # A second registrant replaying the same key cannot grab a second owner.
    second = f"second-{uuid.uuid4().hex[:8]}@finguard.io"
    res = await client.post(
        "/api/v1/identity/register", json=_payload(second, bootstrap_key=_KEY)
    )
    assert res.status_code == 403
