"""Authentication on the inbound Daraja STK callback.

Safaricom does not HMAC-sign callbacks, so the primary control is a source-IP
allowlist; the HMAC signature is optional defence-in-depth. These tests pin:
  * fail-closed when no control is configured (503),
  * IP allowlist enforcement (allowed origin passes, others 403),
  * signature-only mode (no allowlist) still enforces the HMAC.
Uses a minimal app so no DB/auth is needed.
"""
from __future__ import annotations

import hashlib
import hmac
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient

from src.domains.finance import router as finance_router
from src.domains.finance.router import verify_mpesa_signature

_PATH = "/cb"


def _build_app() -> FastAPI:
    app = FastAPI()

    @app.post(_PATH, dependencies=[Depends(verify_mpesa_signature)])
    async def _cb() -> dict[str, bool]:
        return {"ok": True}

    return app


@pytest_asyncio.fixture
async def client(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[AsyncClient]:
    # Reset config to a clean slate; individual tests set what they need.
    monkeypatch.setattr(finance_router.settings, "MPESA_CALLBACK_ALLOWED_IPS", [])
    monkeypatch.setattr(finance_router.settings, "MPESA_CONSUMER_SECRET", "")
    finance_router._mpesa_allowed_networks.cache_clear()
    transport = ASGITransport(app=_build_app())
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    finance_router._mpesa_allowed_networks.cache_clear()


def _set_allowlist(monkeypatch: pytest.MonkeyPatch, ips: list[str]) -> None:
    monkeypatch.setattr(finance_router.settings, "MPESA_CALLBACK_ALLOWED_IPS", ips)
    finance_router._mpesa_allowed_networks.cache_clear()


@pytest.mark.asyncio
async def test_fail_closed_when_unconfigured(client: AsyncClient) -> None:
    res = await client.post(_PATH, json={"Body": {}})
    assert res.status_code == 503


@pytest.mark.asyncio
async def test_ip_allowlist_blocks_foreign_origin(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_allowlist(monkeypatch, ["196.201.214.0/24"])  # Safaricom-style range
    res = await client.post(
        _PATH, json={"Body": {}}, headers={"X-Forwarded-For": "8.8.8.8"}
    )
    assert res.status_code == 403
    assert "allowlist" in res.json()["detail"].lower()


@pytest.mark.asyncio
async def test_ip_allowlist_admits_listed_origin(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_allowlist(monkeypatch, ["196.201.214.0/24"])
    res = await client.post(
        _PATH, json={"Body": {}}, headers={"X-Forwarded-For": "196.201.214.200"}
    )
    assert res.status_code == 200


@pytest.mark.asyncio
async def test_signature_only_mode_requires_valid_hmac(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    secret = "top-secret"
    monkeypatch.setattr(finance_router.settings, "MPESA_CONSUMER_SECRET", secret)
    # No allowlist → the HMAC signature is the sole control and is mandatory.

    body = b'{"Body":{"stkCallback":{}}}'
    good_sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

    missing = await client.post(_PATH, content=body)
    assert missing.status_code == 403

    bad = await client.post(
        _PATH, content=body, headers={"X-Daraja-Signature": "deadbeef"}
    )
    assert bad.status_code == 403

    ok = await client.post(
        _PATH, content=body, headers={"X-Daraja-Signature": good_sig}
    )
    assert ok.status_code == 200
