"""Low-stock alert lifecycle: dedicated type, severity escalation on stockout,
and auto-resolution when stock is replenished above the reorder level."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.domains.alerts.models import AlertSeverity, AlertStatus, AlertType
from src.domains.alerts.service import AlertService
from src.domains.inventory.schemas import InventoryMovementCreate, ProductCreate
from src.domains.inventory.service import InventoryService
from src.domains.inventory.types import MovementReason, MovementType


def _sku() -> str:
    return f"SKU-{uuid.uuid4().hex[:10]}"


async def _product(service: InventoryService):
    return await service.create_product(
        ProductCreate(sku=_sku(), name="Widget", reorder_level=Decimal("5"))
    )


async def _receive(service: InventoryService, pid: uuid.UUID, qty: str, cost: str) -> None:
    await service.record_movement(
        pid,
        InventoryMovementCreate(
            movement_type=MovementType.RECEIPT, quantity=Decimal(qty), unit_cost=Decimal(cost)
        ),
    )


async def _sell(service: InventoryService, pid: uuid.UUID, qty: str) -> None:
    await service.record_movement(
        pid,
        InventoryMovementCreate(
            movement_type=MovementType.SALE, quantity=Decimal(qty), reason=MovementReason.SALE
        ),
    )


def _active_low_stock(alerts, pid: uuid.UUID):
    return [
        a
        for a in alerts
        if a.status == AlertStatus.ACTIVE
        and a.type == AlertType.LOW_STOCK
        and a.metadata_payload.get("product_id") == str(pid)
    ]


@pytest.mark.asyncio
async def test_low_stock_uses_dedicated_type_and_escalates_on_stockout(
    db_session: AsyncSession,
) -> None:
    service = InventoryService(db_session)
    product = await _product(service)
    await _receive(service, product.id, "10", "5")

    # Drop to 4 (≤ reorder 5): a WARNING low-stock alert of the dedicated type.
    await _sell(service, product.id, "6")
    active = _active_low_stock(await AlertService(db_session).list_alerts(AlertStatus.ACTIVE), product.id)
    assert len(active) == 1
    assert active[0].severity == AlertSeverity.WARNING

    # Drop to 0 (hard stockout): the SAME alert escalates to CRITICAL — no duplicate.
    await _sell(service, product.id, "4")
    active = _active_low_stock(await AlertService(db_session).list_alerts(AlertStatus.ACTIVE), product.id)
    assert len(active) == 1
    assert active[0].severity == AlertSeverity.CRITICAL
    assert "Out of stock" in active[0].title


@pytest.mark.asyncio
async def test_replenish_auto_resolves_low_stock(db_session: AsyncSession) -> None:
    service = InventoryService(db_session)
    product = await _product(service)
    await _receive(service, product.id, "10", "5")
    await _sell(service, product.id, "7")  # → 3, low

    assert _active_low_stock(
        await AlertService(db_session).list_alerts(AlertStatus.ACTIVE), product.id
    )

    # Restock back above reorder → the standing alert auto-resolves.
    await _receive(service, product.id, "20", "5")
    assert not _active_low_stock(
        await AlertService(db_session).list_alerts(AlertStatus.ACTIVE), product.id
    )
    resolved = [
        a
        for a in await AlertService(db_session).list_alerts(AlertStatus.RESOLVED)
        if a.type == AlertType.LOW_STOCK and a.metadata_payload.get("product_id") == str(product.id)
    ]
    assert len(resolved) == 1
