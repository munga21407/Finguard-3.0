import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import ConflictError, NotFoundError, UnprocessableError
from src.domains.inventory.models import Product, StockLevel, StockMovement
from src.domains.inventory.repository import ProductRepository, StockRepository
from src.domains.inventory.schemas import InventoryMovementCreate, ProductCreate, ProductUpdate
from src.domains.inventory.types import INBOUND, MovementReason, MovementType


class InventoryService:
    def __init__(self, session: AsyncSession) -> None:
        self._product_repo = ProductRepository(session)
        self._stock_repo = StockRepository(session)
        self._session = session

    async def create_product(self, data: ProductCreate) -> Product:
        if await self._product_repo.get_by_sku(data.sku):
            raise ConflictError(f"Product {data.sku} already exists")
        product = Product(**data.model_dump())
        product = await self._product_repo.create(product)
        await self._session.commit()
        return product

    async def list_products(self, limit: int = 50, offset: int = 0) -> list[Product]:
        return await self._product_repo.list_all(limit=limit, offset=offset)

    async def get_product(self, product_id: uuid.UUID) -> Product:
        product = await self._product_repo.get_by_id(product_id)
        if not product:
            raise NotFoundError("Product not found")
        return product

    async def update_product(self, product_id: uuid.UUID, data: ProductUpdate) -> Product:
        product = await self.get_product(product_id)
        for field, value in data.model_dump(exclude_none=True).items():
            setattr(product, field, value)
        product = await self._product_repo.save(product)
        await self._session.commit()
        return product

    async def get_stock_level(self, product_id: uuid.UUID) -> StockLevel:
        product = await self.get_product(product_id)
        if not product.is_active:
            raise UnprocessableError("Product is inactive")
        level = await self._stock_repo.get_level(product_id)
        if level is None:
            level = StockLevel(product_id=product_id)
            self._session.add(level)
            await self._session.flush()
        return level

    async def record_movement(
        self, product_id: uuid.UUID, data: InventoryMovementCreate
    ) -> StockMovement:
        product = await self.get_product(product_id)
        if not product.is_active:
            raise UnprocessableError("Product is inactive")

        level = await self._stock_repo.get_or_create_level(product_id)
        if data.movement_type == MovementType.ADJUSTMENT and data.quantity == 0:
            raise UnprocessableError("Adjustment quantity must be non-zero")

        delta = self._signed_quantity(data.movement_type, data.quantity)
        if data.movement_type in {MovementType.ISSUE, MovementType.SALE}:
            if level.quantity_on_hand + delta < 0:
                raise UnprocessableError("Insufficient stock for this movement")

        next_sequence = await self._stock_repo.last_sequence(product_id) + 1
        movement = StockMovement(
            product_id=product_id,
            sequence=next_sequence,
            movement_type=data.movement_type,
            movement_reason=data.reason,
            quantity=data.quantity,
            unit_cost=data.unit_cost,
            note=data.note,
            payload={"reason": data.reason.value if data.reason else None},
            occurred_at=datetime.now(UTC),
        )
        await self._stock_repo.append_movement(movement)

        if data.movement_type in INBOUND:
            level.quantity_on_hand += data.quantity
        else:
            level.quantity_on_hand += delta

        if data.unit_cost is not None:
            level.average_cost = data.unit_cost

        await self._stock_repo.save_level(level)
        await self._session.commit()
        return movement

    def _signed_quantity(self, movement_type: MovementType, quantity: Decimal) -> Decimal:
        if movement_type in INBOUND:
            return quantity
        if movement_type == MovementType.ADJUSTMENT:
            return quantity
        return -quantity
