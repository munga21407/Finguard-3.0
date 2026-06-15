"""End-to-end CSRF middleware test over HTTP.

Complements the unit-level decision tests in ``test_csrf.py`` by driving a real
ASGI app through the middleware with httpx: a mutating request is rejected (403)
without a matching double-submit token and accepted with one, while safe methods
and exempt webhook paths always pass.  Uses a minimal app so no DB/auth is needed.
"""
from __future__ import annotations

from typing import Any

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from src.core import csrf
from src.core.csrf import CSRF_COOKIE_NAME, CSRFMiddleware

_TOKEN = "a" * 64
_MUTATE = "/api/v1/finance/budgets"
_WEBHOOK = "/api/v1/finance/mpesa/callback"


def _build_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(CSRFMiddleware)

    @app.post(_MUTATE)
    async def _mutate() -> dict[str, bool]:
        return {"ok": True}

    @app.get(_MUTATE)
    async def _read() -> dict[str, bool]:
        return {"ok": True}

    @app.post(_WEBHOOK)
    async def _webhook() -> dict[str, bool]:
        return {"ok": True}

    return app


@pytest_asyncio.fixture
async def client(monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setattr(csrf.settings, "CSRF_ENABLED", True)  # suite disables it globally
    transport = ASGITransport(app=_build_app())
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_mutation_without_token_is_rejected(client: AsyncClient) -> None:
    resp = await client.post(_MUTATE)
    assert resp.status_code == 403
    assert "missing token" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_mutation_with_mismatched_token_is_rejected(client: AsyncClient) -> None:
    client.cookies.set(CSRF_COOKIE_NAME, _TOKEN)
    resp = await client.post(_MUTATE, headers={"X-CSRF-Token": "b" * 64})
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_mutation_with_matching_token_passes(client: AsyncClient) -> None:
    client.cookies.set(CSRF_COOKIE_NAME, _TOKEN)
    resp = await client.post(_MUTATE, headers={"X-CSRF-Token": _TOKEN})
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


@pytest.mark.asyncio
async def test_safe_method_needs_no_token(client: AsyncClient) -> None:
    assert (await client.get(_MUTATE)).status_code == 200


@pytest.mark.asyncio
async def test_exempt_webhook_passes_without_token(client: AsyncClient) -> None:
    assert (await client.post(_WEBHOOK)).status_code == 200
