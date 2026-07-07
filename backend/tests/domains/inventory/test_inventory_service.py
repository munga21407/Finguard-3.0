import uuid
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import UnprocessableError
from src.domains.inventory.schemas import InventoryMovementCreate, ProductCreate
from src.domains.inventory.service import InventoryService
from src.domains.inventory.types import MovementReason, MovementType, UnitOfMeasure


@pytest.mark.asyncio
async def test_receipt_increases_on_hand_and_sale_cannot_go_negative(db_session: AsyncSession) -> None:
    service = InventoryService(db_session)

    product = await service.create_product(
        ProductCreate(
            sku="SKU-001",
            name="Widget",
            unit=UnitOfMeasure.EACH,
            cost_price=Decimal("10.00"),
            selling_price=Decimal("15.00"),
            reorder_level=Decimal("2"),
            reorder_quantity=Decimal("5"),
        )
    )

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
