from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.domains.audit.models import AuditAction
from src.domains.audit.service import AuditService
from src.domains.identity.dependencies import get_current_user
from src.domains.identity.models import User, UserRole
from src.main import app
from tests.conftest import TestingSessionLocal


def _product_payload() -> dict[str, object]:
    return {
        "sku": f"SKU-{uuid.uuid4().hex[:10]}",
        "name": "Widget",
        "cost_price": "10.00",
        "selling_price": "15.00",
        "reorder_level": "2",
        "reorder_quantity": "5",
    }


async def _create_product(client: AsyncClient) -> str:
    res = await client.post("/api/v1/inventory/products", json=_product_payload())
    assert res.status_code == 201, res.text
    return res.json()["id"]


@pytest.mark.asyncio
async def test_full_movement_lifecycle_as_owner(
    client: AsyncClient, auth_as: Callable[..., User]
) -> None:
    auth_as(UserRole.OWNER)
    product_id = await _create_product(client)

    res = await client.post(
        f"/api/v1/inventory/products/{product_id}/movements",
        json={"movement_type": "receipt", "quantity": "10", "unit_cost": "10.00"},
    )
    assert res.status_code == 201, res.text
    assert res.json()["balance_after"] == "10.000"

    res = await client.post(
        f"/api/v1/inventory/products/{product_id}/adjust",
        json={"quantity": "-3", "reason": "stock_take"},
    )
    assert res.status_code == 201, res.text
    assert res.json()["balance_after"] == "7.000"

    res = await client.get(f"/api/v1/inventory/products/{product_id}/stock")
    assert res.status_code == 200
    assert res.json()["quantity_on_hand"] == "7.000"

    res = await client.get(f"/api/v1/inventory/products/{product_id}/movements")
    assert res.status_code == 200
    assert [m["sequence"] for m in res.json()] == [2, 1]  # desc


@pytest.mark.asyncio
async def test_viewer_cannot_mutate_but_can_read(
    client: AsyncClient, auth_as: Callable[..., User]
) -> None:
    auth_as(UserRole.OWNER)
    product_id = await _create_product(client)

    auth_as(UserRole.VIEWER)
    assert (
        await client.post("/api/v1/inventory/products", json=_product_payload())
    ).status_code == 403
    assert (
        await client.post(
            f"/api/v1/inventory/products/{product_id}/movements",
            json={"movement_type": "issue", "quantity": "1"},
        )
    ).status_code == 403
    assert (
        await client.post(
            f"/api/v1/inventory/products/{product_id}/adjust",
            json={"quantity": "1", "reason": "stock_take"},
        )
    ).status_code == 403
    # Reads are allowed.
    assert (await client.get(f"/api/v1/inventory/products/{product_id}")).status_code == 200
    assert (await client.get("/api/v1/inventory/products")).status_code == 200


@pytest.mark.asyncio
async def test_accountant_can_write_but_not_adjust(
    client: AsyncClient, auth_as: Callable[..., User]
) -> None:
    """Separation of duties: an operator moves stock but only managers+ hold
    INVENTORY_ADJUST (adjustments can create stock from nothing)."""
    auth_as(UserRole.OWNER)
    product_id = await _create_product(client)

    auth_as(UserRole.ACCOUNTANT)
    res = await client.post(
        f"/api/v1/inventory/products/{product_id}/movements",
        json={"movement_type": "receipt", "quantity": "5", "unit_cost": "10"},
    )
    assert res.status_code == 201, res.text
    res = await client.post(
        f"/api/v1/inventory/products/{product_id}/adjust",
        json={"quantity": "-1", "reason": "damage"},
    )
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_movement_validation(client: AsyncClient, auth_as: Callable[..., User]) -> None:
    auth_as(UserRole.OWNER)
    product_id = await _create_product(client)

    # RECEIPT without unit_cost is rejected.
    res = await client.post(
        f"/api/v1/inventory/products/{product_id}/movements",
        json={"movement_type": "receipt", "quantity": "5"},
    )
    assert res.status_code == 422

    # ADJUSTMENT must go through /adjust, not /movements.
    res = await client.post(
        f"/api/v1/inventory/products/{product_id}/movements",
        json={"movement_type": "adjustment", "quantity": "5"},
    )
    assert res.status_code == 422

    # Non-positive quantity is rejected.
    res = await client.post(
        f"/api/v1/inventory/products/{product_id}/movements",
        json={"movement_type": "issue", "quantity": "0"},
    )
    assert res.status_code == 422


@pytest_asyncio.fixture
async def committed_owner() -> AsyncIterator[User]:
    """A persisted OWNER whose id can back an audit row's actor_id FK (the write
    path the real endpoints exercise)."""
    user = User(
        id=uuid.uuid4(),
        email=f"owner-{uuid.uuid4().hex[:8]}@finguard.local",
        hashed_password="x",
        full_name="Inventory Owner",
        role=UserRole.OWNER,
        is_active=True,
        is_verified=True,
    )
    async with TestingSessionLocal() as session:
        session.add(user)
        await session.commit()

    async def _override() -> User:
        return user

    app.dependency_overrides[get_current_user] = _override
    yield user
    app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.asyncio
async def test_movement_writes_audit_row(
    client: AsyncClient, committed_owner: User, db_session: AsyncSession
) -> None:
    product_id = await _create_product(client)
    res = await client.post(
        f"/api/v1/inventory/products/{product_id}/movements",
        json={"movement_type": "receipt", "quantity": "4", "unit_cost": "10"},
    )
    movement_id = res.json()["id"]

    logs, total = await AuditService(db_session).query(action=AuditAction.STOCK_RECEIVED.value)
    assert total >= 1
    entry = next(e for e in logs if e.resource_id == movement_id)
    assert entry.actor_id == committed_owner.id
    assert entry.resource_type == "stock_movement"
