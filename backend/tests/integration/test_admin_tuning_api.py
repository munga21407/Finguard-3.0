"""API tests for the admin tuning / tax-rate router (needs Postgres).

Exercises RBAC (USER_MANAGE) and the happy / 404 / 422 paths via the ASGI client.
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient

from src.domains.identity.models import UserRole
from src.domains.intelligence.tuning import clear_db_overlay

BASE = "/api/v1/intelligence/admin"


@pytest.fixture(autouse=True)
def _reset_overlay() -> None:
    clear_db_overlay()
    yield
    clear_db_overlay()


@pytest.mark.asyncio
async def test_viewer_forbidden(client: AsyncClient, auth_as, tuning_tables: None) -> None:
    auth_as(UserRole.VIEWER)
    res = await client.put(
        f"{BASE}/agent-tuning/reconciler", json={"payload": {"txn_batch": 7}}
    )
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_owner_can_apply_override(client: AsyncClient, auth_as, tuning_tables: None) -> None:
    auth_as(UserRole.OWNER)
    res = await client.put(
        f"{BASE}/agent-tuning/reconciler", json={"payload": {"txn_batch": 7}}
    )
    assert res.status_code == 200
    assert res.json() == {"target": "reconciler", "status": "applied"}


@pytest.mark.asyncio
async def test_unknown_section_404(client: AsyncClient, auth_as, tuning_tables: None) -> None:
    auth_as(UserRole.OWNER)
    res = await client.put(f"{BASE}/agent-tuning/bogus", json={"payload": {}})
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_invalid_override_422(client: AsyncClient, auth_as, tuning_tables: None) -> None:
    auth_as(UserRole.OWNER)
    res = await client.put(
        f"{BASE}/agent-tuning/auditor", json={"payload": {"vat_rate": 1.6}}
    )
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_tax_rate_upsert_then_list(client: AsyncClient, auth_as, tuning_tables: None) -> None:
    auth_as(UserRole.OWNER)
    put = await client.put(
        f"{BASE}/tax-rates/vat_rate", json={"rate": 0.16, "effective_from": "2024-01-01"}
    )
    assert put.status_code == 200

    listed = await client.get(f"{BASE}/tax-rates")
    assert listed.status_code == 200
    body = listed.json()
    assert any(r["rate_key"] == "vat_rate" and r["rate"] == 0.16 for r in body)


@pytest.mark.asyncio
async def test_agent_tuning_view(client: AsyncClient, auth_as, tuning_tables: None) -> None:
    auth_as(UserRole.OWNER)
    res = await client.get(f"{BASE}/agent-tuning")
    assert res.status_code == 200
    body = res.json()
    assert set(body) == {"reconciler", "watchdog", "auditor", "bankability"}
    assert body["reconciler"]["txn_batch"] == 100   # default when no override applied
