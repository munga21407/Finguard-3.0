import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

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
    movement_type: MovementType
    quantity: Decimal
    unit_cost: Decimal | None = None
    reason: MovementReason | None = None
    note: str | None = None


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
    note: str | None
    payload: dict[str, object]
    occurred_at: datetime
    created_at: datetime
