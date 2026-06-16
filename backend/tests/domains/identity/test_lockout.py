"""
Account lockout after repeated failed logins (brute-force protection).
"""
from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from src.core.config import settings


async def _register(client: AsyncClient, email: str) -> None:
    res = await client.post(
        "/api/v1/identity/register",
        json={"email": email, "password": "secure1234", "full_name": "Lock User"},
    )
    assert res.status_code == 201


@pytest.mark.asyncio
async def test_account_locks_after_max_failed_attempts(client: AsyncClient) -> None:
    email = f"lock-{uuid.uuid4().hex[:8]}@finguard.io"
    await _register(client, email)

    # Exhaust the allowed attempts with the wrong password.
    for _ in range(settings.MAX_LOGIN_ATTEMPTS):
        res = await client.post(
            "/api/v1/identity/token", json={"email": email, "password": "wrong-password"}
        )
        assert res.status_code == 401

    # Now locked: even the CORRECT password is rejected with 429.
    locked = await client.post(
        "/api/v1/identity/token", json={"email": email, "password": "secure1234"}
    )
    assert locked.status_code == 429


@pytest.mark.asyncio
async def test_lockout_is_isolated_per_source_ip(client: AsyncClient) -> None:
    """An attacker exhausting attempts from one IP must not lock the victim out.

    Lockout is keyed per (email, source IP), so failures from the attacker's IP
    confine the lock to that IP — the legitimate user logging in from a different
    IP with the correct password still succeeds.
    """
    email = f"dos-{uuid.uuid4().hex[:8]}@finguard.io"
    await _register(client, email)

    # Attacker hammers wrong passwords from one IP until that (email, IP) is locked.
    attacker_ip = {"X-Forwarded-For": "203.0.113.10"}
    for _ in range(settings.MAX_LOGIN_ATTEMPTS):
        res = await client.post(
            "/api/v1/identity/token",
            json={"email": email, "password": "wrong-password"},
            headers=attacker_ip,
        )
        assert res.status_code == 401
    locked = await client.post(
        "/api/v1/identity/token",
        json={"email": email, "password": "secure1234"},
        headers=attacker_ip,
    )
    assert locked.status_code == 429

    # Victim, from a different IP, logs in successfully with the correct password.
    victim_ip = {"X-Forwarded-For": "198.51.100.20"}
    ok = await client.post(
        "/api/v1/identity/token",
        json={"email": email, "password": "secure1234"},
        headers=victim_ip,
    )
    assert ok.status_code == 200


@pytest.mark.asyncio
async def test_successful_login_resets_attempt_counter(client: AsyncClient) -> None:
    email = f"reset-{uuid.uuid4().hex[:8]}@finguard.io"
    await _register(client, email)

    # Fail a few times, but stay under the threshold.
    for _ in range(settings.MAX_LOGIN_ATTEMPTS - 1):
        res = await client.post(
            "/api/v1/identity/token", json={"email": email, "password": "wrong-password"}
        )
        assert res.status_code == 401

    # A correct login succeeds and clears the counter.
    ok = await client.post(
        "/api/v1/identity/token", json={"email": email, "password": "secure1234"}
    )
    assert ok.status_code == 200

    # The counter was reset, so we can fail again without being locked.
    for _ in range(settings.MAX_LOGIN_ATTEMPTS - 1):
        res = await client.post(
            "/api/v1/identity/token", json={"email": email, "password": "wrong-password"}
        )
        assert res.status_code == 401
