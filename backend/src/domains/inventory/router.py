import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.domains.audit.models import AuditAction
from src.domains.audit.service import AuditService
from src.domains.identity.dependencies import RequireInventoryRead, RequireInventoryWrite
from src.domains.inventory.schemas import (
    InventoryMovementCreate,
    ProductCreate,
    ProductResponse,
    ProductUpdate,
    StockLevelResponse,
    StockMovementResponse,
)
from src.domains.inventory.service import InventoryService
from src.infrastructure.database.postgres import get_db

router = APIRouter()

DBSession = Annotated[AsyncSession, Depends(get_db)]


@router.post("/products", response_model=ProductResponse, status_code=201)
async def create_product(
    data: ProductCreate, db: DBSession, current_user: RequireInventoryWrite
) -> ProductResponse:
    product = await InventoryService(db).create_product(data)
    result = ProductResponse.model_validate(product)
    await AuditService(db).record_user_action_safe(
        current_user,
        AuditAction.PRODUCT_CREATED,
        "product",
        resource_id=product.id,
        metadata={"sku": product.sku, "name": product.name},
    )
    return result


@router.get("/products", response_model=list[ProductResponse])
async def list_products(
    db: DBSession,
    _: RequireInventoryRead,
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
) -> list[ProductResponse]:
    products = await InventoryService(db).list_products(limit=limit, offset=offset)
    return [ProductResponse.model_validate(product) for product in products]


@router.get("/products/{product_id}", response_model=ProductResponse)
async def get_product(
    product_id: uuid.UUID, db: DBSession, _: RequireInventoryRead
) -> ProductResponse:
    product = await InventoryService(db).get_product(product_id)
    return ProductResponse.model_validate(product)


@router.patch("/products/{product_id}", response_model=ProductResponse)
async def update_product(
    product_id: uuid.UUID,
    data: ProductUpdate,
    db: DBSession,
    current_user: RequireInventoryWrite,
) -> ProductResponse:
    product = await InventoryService(db).update_product(product_id, data)
    result = ProductResponse.model_validate(product)
    await AuditService(db).record_user_action_safe(
        current_user,
        AuditAction.PRODUCT_UPDATED,
        "product",
        resource_id=product.id,
        metadata=data.model_dump(exclude_none=True, mode="json"),
    )
    return result


@router.get("/products/{product_id}/stock", response_model=StockLevelResponse)
async def get_stock_level(
    product_id: uuid.UUID, db: DBSession, _: RequireInventoryRead
) -> StockLevelResponse:
    level = await InventoryService(db).get_stock_level(product_id)
    return StockLevelResponse.model_validate(level)


@router.post("/products/{product_id}/movements", response_model=StockMovementResponse, status_code=201)
async def record_movement(
    product_id: uuid.UUID,
    data: InventoryMovementCreate,
    db: DBSession,
    current_user: RequireInventoryWrite,
) -> StockMovementResponse:
    movement = await InventoryService(db).record_movement(product_id, data)
    result = StockMovementResponse.model_validate(movement)
    action = {
        MovementType.RECEIPT: AuditAction.STOCK_RECEIVED,
        MovementType.ISSUE: AuditAction.STOCK_ISSUED,
        MovementType.SALE: AuditAction.STOCK_ISSUED,
        MovementType.RETURN_IN: AuditAction.STOCK_RECEIVED,
        MovementType.ADJUSTMENT: AuditAction.STOCK_ADJUSTED,
    }.get(data.movement_type, AuditAction.STOCK_ADJUSTED)
    await AuditService(db).record_user_action_safe(
        current_user,
        action,
        "stock_movement",
        resource_id=movement.id,
        metadata={"product_id": str(product_id), "quantity": str(data.quantity)},
    )
    return result
