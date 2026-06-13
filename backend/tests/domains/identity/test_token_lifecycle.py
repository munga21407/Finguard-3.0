"""
Refresh-token rotation, reuse detection, and logout revocation.

  * Each refresh rotates the token and blacklists the consumed one.
  * Replaying a rotated (or logged-out) refresh token is rejected.
"""
from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient


async def _register_and_login(client: AsyncClient, email: str) -> dict:
    await client.post(
        "/api/v1/identity/register",
        json={"email": email, "password": "secure1234", "full_name": "Token User"},
    )
    res = await client.post(
        "/api/v1/identity/token", json={"email": email, "password": "secure1234"}
    )
    assert res.status_code == 200
    return res.json()


@pytest.mark.asyncio
async def test_refresh_rotates_and_detects_reuse(client: AsyncClient) -> None:
    email = f"rotate-{uuid.uuid4().hex[:8]}@finguard.io"
    tokens = await _register_and_login(client, email)
    original_refresh = tokens["refresh_token"]

    # First refresh succeeds and issues a NEW refresh token.
    first = await client.post(
        "/api/v1/identity/token/refresh", json={"refresh_token": original_refresh}
    )
    assert first.status_code == 200
    rotated_refresh = first.json()["refresh_token"]
    assert rotated_refresh != original_refresh

    # Replaying the original (now-rotated) token is rejected — reuse detection.
    reuse = await client.post(
        "/api/v1/identity/token/refresh", json={"refresh_token": original_refresh}
    )
    assert reuse.status_code == 401

    # The rotated token still works.
    third = await client.post(
        "/api/v1/identity/token/refresh", json={"refresh_token": rotated_refresh}
    )
    assert third.status_code == 200


@pytest.mark.asyncio
async def test_logout_revokes_refresh_token(client: AsyncClient) -> None:
    email = f"logout-{uuid.uuid4().hex[:8]}@finguard.io"
    tokens = await _register_and_login(client, email)

    out = await client.post(
        "/api/v1/identity/logout",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
        json={"refresh_token": tokens["refresh_token"]},
    )
    assert out.status_code == 204

    # The refresh token can no longer mint new access tokens after logout.
    res = await client.post(
        "/api/v1/identity/token/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert res.status_code == 401
