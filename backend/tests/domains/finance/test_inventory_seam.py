"""Finance ↔ inventory seams: atomic stock purchase and the COGS read path."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domains.finance.schemas import ExpenseCreate, StockPurchaseCreate
from src.domains.finance.service import FinanceService
from src.domains.finance.types import VaultType
from src.domains.inventory.models import StockMovement
from src.domains.inventory.schemas import InventoryMovementCreate, ProductCreate
from src.domains.inventory.service import InventoryService
from src.domains.inventory.types import MovementReason, MovementType


def _sku() -> str:
    return f"SKU-{uuid.uuid4().hex[:10]}"


@pytest.mark.asyncio
async def test_stock_purchase_books_expense_and_receipt_atomically(
    db_session: AsyncSession,
) -> None:
    product = await InventoryService(db_session).create_product(
        ProductCreate(sku=_sku(), name="Bolt")
    )

    expense, movement = await FinanceService(db_session).create_stock_purchase(
        StockPurchaseCreate(
            expense=ExpenseCreate(category="stock", amount=Decimal("500"), vault=VaultType.CASH),
            product_id=product.id,
            quantity=Decimal("50"),
            unit_cost=Decimal("10"),
        )
    )

    # The RECEIPT links back to the expense (reference stored on inventory's side).
    assert movement.movement_type == MovementType.RECEIPT
    assert movement.reference_type == "expense"
    assert movement.reference_id == expense.id

    level = await InventoryService(db_session).get_stock_level(product.id)
    assert level.quantity_on_hand == Decimal("50")
    assert level.average_cost == Decimal("10.00")

    # Both rows are committed and joined only by reference_id.
    rows = (
        (
            await db_session.execute(
                select(StockMovement).where(StockMovement.reference_id == expense.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_cogs_for_invoice_reads_inventory_average_cost(db_session: AsyncSession) -> None:
    inventory = InventoryService(db_session)
    product = await inventory.create_product(ProductCreate(sku=_sku(), name="Nut"))
    await inventory.record_movement(
        product.id,
        InventoryMovementCreate(
            movement_type=MovementType.RECEIPT, quantity=Decimal("100"), unit_cost=Decimal("4")
        ),
    )

    invoice_id = uuid.uuid4()
    await inventory.record_movement(
        product.id,
        InventoryMovementCreate(
            movement_type=MovementType.SALE,
            quantity=Decimal("30"),
            reason=MovementReason.SALE,
            reference_type="invoice",
            reference_id=invoice_id,
        ),
    )

    # 30 sold × 4.00 average cost = 120.00 COGS, read by finance from inventory.
    cogs = await FinanceService(db_session).cogs_for_invoice(invoice_id)
    assert cogs == Decimal("120.00")
    # An unrelated invoice has no tracked sales → zero COGS.
    assert await FinanceService(db_session).cogs_for_invoice(uuid.uuid4()) == Decimal("0.00")


@pytest.mark.asyncio
async def test_cogs_is_point_in_time_not_current_cost(db_session: AsyncSession) -> None:
    """COGS is stamped at sale time, so restocking at a new price afterwards must
    not retroactively change a past sale's cost of goods sold."""
    inventory = InventoryService(db_session)
    product = await inventory.create_product(ProductCreate(sku=_sku(), name="Washer"))
    await inventory.record_movement(
        product.id,
        InventoryMovementCreate(
            movement_type=MovementType.RECEIPT, quantity=Decimal("100"), unit_cost=Decimal("4")
        ),
    )
    invoice_id = uuid.uuid4()
    await inventory.record_movement(
        product.id,
        InventoryMovementCreate(
            movement_type=MovementType.SALE,
            quantity=Decimal("30"),
            reason=MovementReason.SALE,
            reference_type="invoice",
            reference_id=invoice_id,
        ),
    )
    # Restock at a much higher price — the weighted-average cost jumps.
    await inventory.record_movement(
        product.id,
        InventoryMovementCreate(
            movement_type=MovementType.RECEIPT, quantity=Decimal("100"), unit_cost=Decimal("20")
        ),
    )
    level = await inventory.get_stock_level(product.id)
    assert level.average_cost > Decimal("4.00")  # current cost has moved…

    # …but the historical sale's COGS stays at the cost-at-sale (30 × 4 = 120).
    assert await FinanceService(db_session).cogs_for_invoice(invoice_id) == Decimal("120.00")
