from __future__ import annotations

import uuid
from collections.abc import Callable
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.domains.alerts.models import AlertStatus
from src.domains.alerts.service import AlertService
from src.domains.identity.models import User, UserRole
from src.domains.inventory.schemas import (
    InventoryMovementCreate,
    ProductCreate,
    StockAdjustmentCreate,
)
from src.domains.inventory.service import InventoryService
from src.domains.inventory.types import MovementReason, MovementType, UnitOfMeasure


def _sku() -> str:
    return f"SKU-{uuid.uuid4().hex[:10]}"


async def _product(service: InventoryService, **overrides: object):
    data = {
        "sku": _sku(),
        "name": "Widget",
        "unit": UnitOfMeasure.EACH,
        "reorder_level": Decimal("5"),
        "reorder_quantity": Decimal("10"),
    }
    data.update(overrides)
    return await service.create_product(ProductCreate(**data))  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_valuation_and_low_stock_service(db_session: AsyncSession) -> None:
    service = InventoryService(db_session)
    product = await _product(service, category="hardware")
    await service.record_movement(
        product.id,
        InventoryMovementCreate(
            movement_type=MovementType.RECEIPT, quantity=Decimal("10"), unit_cost=Decimal("20")
        ),
    )

    valuation = await service.valuation_report()
    # 10 on hand × 20 avg cost = 200, attributed to the "hardware" category.
    line = next(c for c in valuation.categories if c.category == "hardware")
    assert line.value == Decimal("200.00")
    assert valuation.total_value >= Decimal("200.00")

    # Not low yet (10 > reorder 5); after issuing 6 it drops to 4 ≤ 5.
    assert all(item.product_id != product.id for item in await service.low_stock_report())
    await service.record_movement(
        product.id,
        InventoryMovementCreate(
            movement_type=MovementType.SALE, quantity=Decimal("6"), reason=MovementReason.SALE
        ),
    )
    low = await service.low_stock_report()
    assert any(item.product_id == product.id and item.quantity_on_hand == Decimal("4") for item in low)


@pytest.mark.asyncio
async def test_low_stock_movement_raises_idempotent_alert(db_session: AsyncSession) -> None:
    service = InventoryService(db_session)
    product = await _product(service)
    await service.record_movement(
        product.id,
        InventoryMovementCreate(
            movement_type=MovementType.RECEIPT, quantity=Decimal("10"), unit_cost=Decimal("5")
        ),
    )
    # Cross below reorder level (10 → 3).
    await service.record_movement(
        product.id,
        InventoryMovementCreate(
            movement_type=MovementType.SALE, quantity=Decimal("7"), reason=MovementReason.SALE
        ),
    )
    # A further issue keeps it low but must NOT spawn a second alert (idempotent).
    await service.adjust_stock(
        product.id,
        StockAdjustmentCreate(quantity=Decimal("-1"), reason=MovementReason.DAMAGE),
    )

    alerts = await AlertService(db_session).list_alerts(AlertStatus.ACTIVE)
    mine = [
        a for a in alerts if a.metadata_payload.get("product_id") == str(product.id)
    ]
    assert len(mine) == 1
    assert mine[0].metadata_payload["kind"] == "low_stock"


@pytest.mark.asyncio
async def test_reports_endpoints_rbac(
    client: AsyncClient, auth_as: Callable[..., User]
) -> None:
    auth_as(UserRole.OWNER)
    created = await client.post(
        "/api/v1/inventory/products",
        json={"sku": _sku(), "name": "W", "reorder_level": "5", "reorder_quantity": "10"},
    )
    product_id = created.json()["id"]
    await client.post(
        f"/api/v1/inventory/products/{product_id}/movements",
        json={"movement_type": "receipt", "quantity": "2", "unit_cost": "10"},
    )

    assert (await client.get("/api/v1/inventory/levels")).status_code == 200
    val = await client.get("/api/v1/inventory/reports/valuation")
    assert val.status_code == 200 and "total_value" in val.json()
    low = await client.get("/api/v1/inventory/reports/low-stock")
    assert low.status_code == 200
    assert any(i["product_id"] == product_id for i in low.json())

    # A viewer can read reports but never mutate.
    auth_as(UserRole.VIEWER)
    assert (await client.get("/api/v1/inventory/reports/valuation")).status_code == 200
