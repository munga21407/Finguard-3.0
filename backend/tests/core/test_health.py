"""Health probe endpoints."""
from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_liveness(client: AsyncClient) -> None:
    res = await client.get("/health/live")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_readiness_reports_checks(client: AsyncClient) -> None:
    # Readiness returns 200 when deps are reachable, 503 when degraded — either
    # way the body enumerates the dependency checks.
    res = await client.get("/health/ready")
    assert res.status_code in (200, 503)
    body = res.json()
    assert body["status"] in ("ready", "degraded")
    # All four backing services are enumerated (Mongo + RabbitMQ were previously
    # unchecked — a degraded broker/store would have shown a false "ready").
    for dep in ("postgres", "redis", "mongodb", "rabbitmq"):
        assert dep in body["checks"]
