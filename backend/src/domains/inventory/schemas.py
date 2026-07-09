import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, model_validator

from src.domains.inventory.types import MovementReason, MovementType, UnitOfMeasure


class ProductCreate(BaseModel):
    sku: str
    name: str
    description: str | None = None
    unit: UnitOfMeasure = UnitOfMeasure.EACH
    category: str | None = None
    cost_price: Decimal = Decimal("0")
    selling_price: Decimal = Decimal("0")
    reorder_level: Decimal = Decimal("0")
    reorder_quantity: Decimal = Decimal("0")
    barcode: str | None = None
    is_active: bool = True


class ProductUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    unit: UnitOfMeasure | None = None
    category: str | None = None
    cost_price: Decimal | None = None
    selling_price: Decimal | None = None
    reorder_level: Decimal | None = None
    reorder_quantity: Decimal | None = None
    barcode: str | None = None
    is_active: bool | None = None


class ProductResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    sku: str
    name: str
    description: str | None
    unit: UnitOfMeasure
    category: str | None
    cost_price: Decimal
    selling_price: Decimal
    reorder_level: Decimal
    reorder_quantity: Decimal
    barcode: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class InventoryMovementCreate(BaseModel):
    """A receipt/issue/sale/return. Adjustments go through
    :class:`StockAdjustmentCreate` (they need a reason + a signed delta)."""

    movement_type: MovementType
    quantity: Decimal
    unit_cost: Decimal | None = None
    reason: MovementReason | None = None
    note: str | None = None
    reference_type: str | None = None
    reference_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def _check(self) -> "InventoryMovementCreate":
        if self.movement_type == MovementType.ADJUSTMENT:
            raise ValueError("Use the adjust endpoint for stock adjustments")
        if self.quantity <= 0:
            raise ValueError("quantity must be positive")
        if self.movement_type == MovementType.RECEIPT and self.unit_cost is None:
            raise ValueError("unit_cost is required for a RECEIPT")
        return self


class StockAdjustmentCreate(BaseModel):
    """Stock-take correction. ``quantity`` is a signed delta (negative writes
    stock off; positive writes it up). A reason is mandatory."""

    quantity: Decimal
    reason: MovementReason
    note: str | None = None

    @model_validator(mode="after")
    def _check(self) -> "StockAdjustmentCreate":
        if self.quantity == 0:
            raise ValueError("adjustment quantity must be non-zero")
        return self


class StockLevelResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    product_id: uuid.UUID
    location_id: uuid.UUID | None
    quantity_on_hand: Decimal
    quantity_reserved: Decimal
    average_cost: Decimal
    updated_at: datetime


class StockMovementResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    product_id: uuid.UUID
    sequence: int
    movement_type: MovementType
    movement_reason: MovementReason | None
    quantity: Decimal
    unit_cost: Decimal | None
    balance_after: Decimal
    reference_type: str | None
    reference_id: uuid.UUID | None
    note: str | None
    payload: dict[str, object]
    occurred_at: datetime
    created_at: datetime


class StockLevelView(BaseModel):
    """One product's on-hand snapshot for the /levels overview."""

    product_id: uuid.UUID
    sku: str
    name: str
    category: str | None
    quantity_on_hand: Decimal
    quantity_reserved: Decimal
    average_cost: Decimal
    reorder_level: Decimal


class ValuationCategoryLine(BaseModel):
    category: str
    quantity: Decimal
    value: Decimal


class ValuationReport(BaseModel):
    total_value: Decimal
    categories: list[ValuationCategoryLine]


class LowStockItem(BaseModel):
    product_id: uuid.UUID
    sku: str
    name: str
    quantity_on_hand: Decimal
    reorder_level: Decimal
    reorder_quantity: Decimal
