import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domains.inventory.models import Product, StockLevel, StockMovement


class ProductRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, product_id: uuid.UUID) -> Product | None:
        return await self._session.get(Product, product_id)

    async def get_by_sku(self, sku: str) -> Product | None:
        result = await self._session.execute(select(Product).where(Product.sku == sku))
        return result.scalar_one_or_none()

    async def list_all(self, limit: int = 50, offset: int = 0) -> list[Product]:
        result = await self._session.execute(
            select(Product).order_by(Product.created_at.desc()).limit(limit).offset(offset)
        )
        return list(result.scalars().all())

    async def create(self, product: Product) -> Product:
        self._session.add(product)
        await self._session.flush()
        await self._session.refresh(product)
        return product

    async def save(self, product: Product) -> Product:
        await self._session.flush()
        await self._session.refresh(product)
        return product


class StockRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_level_for_update(self, product_id: uuid.UUID) -> StockLevel | None:
        result = await self._session.execute(
            select(StockLevel)
            .where(StockLevel.product_id == product_id)
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def get_or_create_level(self, product_id: uuid.UUID) -> StockLevel:
        level = await self.get_level_for_update(product_id)
        if level is not None:
            return level
        level = StockLevel(product_id=product_id)
        self._session.add(level)
        await self._session.flush()
        await self._session.refresh(level)
        return level

    async def get_level(self, product_id: uuid.UUID) -> StockLevel | None:
        result = await self._session.execute(select(StockLevel).where(StockLevel.product_id == product_id))
        return result.scalar_one_or_none()

    async def save_level(self, level: StockLevel) -> StockLevel:
        await self._session.flush()
        await self._session.refresh(level)
        return level

    async def last_sequence(self, product_id: uuid.UUID) -> int:
        result = await self._session.execute(
            select(StockMovement.sequence)
            .where(StockMovement.product_id == product_id)
            .order_by(StockMovement.sequence.desc())
            .limit(1)
        )
        return int(result.scalar_one_or_none() or 0)

    async def append_movement(self, movement: StockMovement) -> StockMovement:
        self._session.add(movement)
        await self._session.flush()
        await self._session.refresh(movement)
        return movement
