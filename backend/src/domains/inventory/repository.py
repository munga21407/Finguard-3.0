import uuid
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domains.inventory.models import Product, StockLevel, StockMovement
from src.domains.inventory.types import MovementType


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
            select(StockLevel).where(StockLevel.product_id == product_id).with_for_update()
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
        result = await self._session.execute(
            select(StockLevel).where(StockLevel.product_id == product_id)
        )
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

    async def list_movements(
        self, product_id: uuid.UUID, limit: int = 50, offset: int = 0
    ) -> list[StockMovement]:
        result = await self._session.execute(
            select(StockMovement)
            .where(StockMovement.product_id == product_id)
            .order_by(StockMovement.sequence.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def list_levels_with_products(
        self, limit: int = 100, offset: int = 0
    ) -> list[tuple[Product, StockLevel]]:
        """Every active product with its current level (0 on-hand for products
        that have never had a movement) — the on-hand snapshot + valuation base."""
        result = await self._session.execute(
            select(Product, StockLevel)
            .outerjoin(StockLevel, StockLevel.product_id == Product.id)
            .where(Product.is_active.is_(True))
            .order_by(Product.sku)
            .limit(limit)
            .offset(offset)
        )
        rows: list[tuple[Product, StockLevel]] = []
        for product, level in result.all():
            # A product that has never had a movement has no level row yet — treat
            # it as an explicit zero level (ORM defaults only apply at flush time).
            rows.append(
                (
                    product,
                    level
                    or StockLevel(
                        product_id=product.id,
                        quantity_on_hand=Decimal("0"),
                        quantity_reserved=Decimal("0"),
                        average_cost=Decimal("0"),
                    ),
                )
            )
        return rows

    async def list_low_stock(self) -> list[tuple[Product, Decimal]]:
        """Active products whose on-hand is at/below a positive reorder level
        (reorder_level == 0 means 'no reorder policy' and is excluded)."""
        on_hand = func.coalesce(StockLevel.quantity_on_hand, 0)
        result = await self._session.execute(
            select(Product, on_hand)
            .outerjoin(StockLevel, StockLevel.product_id == Product.id)
            .where(Product.is_active.is_(True))
            .where(Product.reorder_level > 0)
            .where(on_hand <= Product.reorder_level)
            .order_by(Product.sku)
        )
        return [(product, Decimal(str(qty))) for product, qty in result.all()]

    async def cogs_for_reference(self, reference_type: str, reference_id: uuid.UUID) -> Decimal:
        """Σ(movement.quantity × unit_cost) for the SALE movements linked to a
        given finance reference. ``unit_cost`` is the weighted-average cost stamped
        on the sale *at sale time*, so COGS is point-in-time and immune to later
        restocks at a different price."""
        result = await self._session.execute(
            select(
                func.coalesce(
                    func.sum(
                        StockMovement.quantity * func.coalesce(StockMovement.unit_cost, 0)
                    ),
                    0,
                )
            )
            .where(StockMovement.movement_type == MovementType.SALE)
            .where(StockMovement.reference_type == reference_type)
            .where(StockMovement.reference_id == reference_id)
        )
        return Decimal(str(result.scalar_one())).quantize(Decimal("0.01"))
