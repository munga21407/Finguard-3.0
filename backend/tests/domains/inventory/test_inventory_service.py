from __future__ import annotations

import asyncio
import uuid
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import UnprocessableError
from src.domains.inventory.schemas import (
    InventoryMovementCreate,
    ProductCreate,
    StockAdjustmentCreate,
)
from src.domains.inventory.service import InventoryService
from src.domains.inventory.types import MovementReason, MovementType, UnitOfMeasure
from tests.conftest import TestingSessionLocal


def _sku() -> str:
    return f"SKU-{uuid.uuid4().hex[:10]}"


async def _make_product(service: InventoryService, **overrides: object):
    data = {
        "sku": _sku(),
        "name": "Widget",
        "unit": UnitOfMeasure.EACH,
        "cost_price": Decimal("10.00"),
        "selling_price": Decimal("15.00"),
        "reorder_level": Decimal("2"),
        "reorder_quantity": Decimal("5"),
    }
    data.update(overrides)
    return await service.create_product(ProductCreate(**data))  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_receipt_increases_on_hand_and_sale_cannot_go_negative(
    db_session: AsyncSession,
) -> None:
    service = InventoryService(db_session)
    product = await _make_product(service)

    await service.record_movement(
        product.id,
        InventoryMovementCreate(
            movement_type=MovementType.RECEIPT,
            quantity=Decimal("10"),
            unit_cost=Decimal("10.00"),
            reason=MovementReason.PURCHASE,
            note="initial stock",
        ),
    )

    level = await service.get_stock_level(product.id)
    assert level.quantity_on_hand == Decimal("10")
    assert level.average_cost == Decimal("10.00")

    with pytest.raises(UnprocessableError):
        await service.record_movement(
            product.id,
            InventoryMovementCreate(
                movement_type=MovementType.SALE,
                quantity=Decimal("11"),
                reason=MovementReason.SALE,
            ),
        )

    # The rejected sale wrote no movement: the ledger still has exactly the receipt.
    movements = await service.list_movements(product.id)
    assert [m.sequence for m in movements] == [1]
    assert movements[0].balance_after == Decimal("10")


@pytest.mark.asyncio
async def test_weighted_average_cost(db_session: AsyncSession) -> None:
    service = InventoryService(db_session)
    product = await _make_product(service)

    await service.record_movement(
        product.id,
        InventoryMovementCreate(
            movement_type=MovementType.RECEIPT, quantity=Decimal("10"), unit_cost=Decimal("100")
        ),
    )
    await service.record_movement(
        product.id,
        InventoryMovementCreate(
            movement_type=MovementType.RECEIPT, quantity=Decimal("10"), unit_cost=Decimal("120")
        ),
    )

    level = await service.get_stock_level(product.id)
    assert level.quantity_on_hand == Decimal("20")
    assert level.average_cost == Decimal("110.00")

    # A sale consumes stock but must NOT move the weighted-average cost.
    await service.record_movement(
        product.id,
        InventoryMovementCreate(
            movement_type=MovementType.SALE, quantity=Decimal("5"), reason=MovementReason.SALE
        ),
    )
    level = await service.get_stock_level(product.id)
    assert level.quantity_on_hand == Decimal("15")
    assert level.average_cost == Decimal("110.00")


@pytest.mark.asyncio
async def test_adjustment_requires_reason_and_moves_both_directions(
    db_session: AsyncSession,
) -> None:
    service = InventoryService(db_session)
    product = await _make_product(service)
    await service.record_movement(
        product.id,
        InventoryMovementCreate(
            movement_type=MovementType.RECEIPT, quantity=Decimal("10"), unit_cost=Decimal("10")
        ),
    )

    # A positive adjustment writes stock up; a negative one writes it down.
    await service.adjust_stock(
        product.id,
        StockAdjustmentCreate(quantity=Decimal("3"), reason=MovementReason.STOCK_TAKE),
    )
    level = await service.get_stock_level(product.id)
    assert level.quantity_on_hand == Decimal("13")

    await service.adjust_stock(
        product.id,
        StockAdjustmentCreate(quantity=Decimal("-4"), reason=MovementReason.DAMAGE),
    )
    level = await service.get_stock_level(product.id)
    assert level.quantity_on_hand == Decimal("9")

    # The ledger stores positive quantities; direction is captured in balance_after.
    movements = await service.list_movements(product.id)
    assert all(m.quantity > 0 for m in movements)


@pytest.mark.asyncio
async def test_adjustment_cannot_drive_negative(db_session: AsyncSession) -> None:
    service = InventoryService(db_session)
    product = await _make_product(service)
    await service.record_movement(
        product.id,
        InventoryMovementCreate(
            movement_type=MovementType.RECEIPT, quantity=Decimal("5"), unit_cost=Decimal("10")
        ),
    )
    with pytest.raises(UnprocessableError):
        await service.adjust_stock(
            product.id,
            StockAdjustmentCreate(quantity=Decimal("-6"), reason=MovementReason.THEFT),
        )


@pytest.mark.asyncio
async def test_projection_equals_ledger_fold(db_session: AsyncSession) -> None:
    service = InventoryService(db_session)
    product = await _make_product(service)
    for qty, mtype in [
        (Decimal("10"), MovementType.RECEIPT),
        (Decimal("3"), MovementType.SALE),
        (Decimal("2"), MovementType.RETURN_IN),
    ]:
        await service.record_movement(
            product.id,
            InventoryMovementCreate(
                movement_type=mtype,
                quantity=qty,
                unit_cost=Decimal("10") if mtype == MovementType.RECEIPT else None,
                reason=MovementReason.SALE if mtype == MovementType.SALE else None,
            ),
        )

    level = await service.get_stock_level(product.id)
    movements = sorted(await service.list_movements(product.id), key=lambda m: m.sequence)

    # Sequence is gap-free and the last snapshot equals the materialized on-hand.
    assert [m.sequence for m in movements] == [1, 2, 3]
    assert movements[-1].balance_after == level.quantity_on_hand == Decimal("9")


@pytest.mark.asyncio
async def test_concurrent_issues_cannot_oversell() -> None:
    """Two overlapping issues that together exceed on-hand: the FOR UPDATE lock on
    the StockLevel row serialises them so exactly one succeeds (the money-path
    guarantee, mirroring the vault-transfer overdraw test)."""
    async with TestingSessionLocal() as session:
        product = await _make_product(InventoryService(session))
        await InventoryService(session).record_movement(
            product.id,
            InventoryMovementCreate(
                movement_type=MovementType.RECEIPT, quantity=Decimal("10"), unit_cost=Decimal("10")
            ),
        )

    async def _issue() -> object:
        async with TestingSessionLocal() as session:
            return await InventoryService(session).record_movement(
                product.id,
                InventoryMovementCreate(
                    movement_type=MovementType.SALE,
                    quantity=Decimal("7"),
                    reason=MovementReason.SALE,
                ),
            )

    results = await asyncio.gather(_issue(), _issue(), return_exceptions=True)
    successes = [r for r in results if not isinstance(r, Exception)]
    failures = [r for r in results if isinstance(r, Exception)]
    assert len(successes) == 1, "exactly one concurrent issue should succeed"
    assert len(failures) == 1
    assert isinstance(failures[0], UnprocessableError)

    async with TestingSessionLocal() as session:
        level = await InventoryService(session).get_stock_level(product.id)
        assert level.quantity_on_hand == Decimal("3")
