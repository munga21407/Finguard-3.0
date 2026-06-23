"""GenUI render-crash telemetry endpoint (POST /intelligence/genui/error).

The frontend error boundary posts here when a generative widget crashes; the
endpoint records it to operational telemetry and returns 202 without ever
failing the page.  Attribution requires an authenticated session.
"""
from __future__ import annotations

from collections.abc import Callable

import pytest
from httpx import AsyncClient

from src.domains.identity.models import User, UserRole


@pytest.mark.asyncio
async def test_genui_error_report_accepted(
    client: AsyncClient, auth_as: Callable[..., User]
) -> None:
    auth_as(UserRole.VIEWER)
    res = await client.post(
        "/api/v1/intelligence/genui/error",
        json={
            "component_id": "TrendChart",
            "message": "Cannot read properties of undefined (reading 'data')",
            "component_stack": "at TrendChart\n  at GenUiBoundary",
            "pathname": "/dashboard/command-center",
        },
    )
    assert res.status_code == 202
    assert res.json()["status"] == "accepted"


@pytest.mark.asyncio
async def test_genui_error_requires_authentication(client: AsyncClient) -> None:
    # No auth override on this client → the endpoint must reject anonymous reports.
    res = await client.post(
        "/api/v1/intelligence/genui/error",
        json={"component_id": "X", "message": "boom"},
    )
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_genui_error_validates_payload(
    client: AsyncClient, auth_as: Callable[..., User]
) -> None:
    auth_as(UserRole.VIEWER)
    # Missing the required ``message`` field → 422.
    res = await client.post(
        "/api/v1/intelligence/genui/error", json={"component_id": "X"}
    )
    assert res.status_code == 422
