import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import ConflictError, NotFoundError, UnprocessableError
from src.domains.alerts.models import AlertSeverity, AlertType
from src.domains.alerts.schemas import AlertCreate
from src.domains.alerts.service import AlertService
from src.domains.inventory.models import Product, StockLevel, StockMovement
from src.domains.inventory.repository import ProductRepository, StockRepository
from src.domains.inventory.schemas import (
    InventoryMovementCreate,
    LowStockItem,
    ProductCreate,
    ProductUpdate,
    StockAdjustmentCreate,
    StockLevelView,
    ValuationCategoryLine,
    ValuationReport,
)
from src.domains.inventory.types import INBOUND, MovementReason, MovementType

logger = structlog.get_logger(__name__)

_CENTS = Decimal("0.01")


def _weighted_avg(
    qty_before: Decimal, avg_before: Decimal, qty_in: Decimal, cost_in: Decimal
) -> Decimal:
    """New weighted-average unit cost after receiving ``qty_in`` at ``cost_in``.

    Falls back to the incoming cost when there is no prior stock to average
    against (guards the zero/negative denominator)."""
    total_qty = qty_before + qty_in
    if total_qty <= 0:
        return cost_in.quantize(_CENTS)
    total_value = qty_before * avg_before + qty_in * cost_in
    return (total_value / total_qty).quantize(_CENTS)


@dataclass(frozen=True)
class _LowStockSignal:
    """Snapshot captured before commit so the post-commit alert never has to
    lazy-load an expired ORM object."""

    product_id: uuid.UUID
    sku: str
    name: str
    on_hand: Decimal
    reorder_level: Decimal


class InventoryService:
    def __init__(self, session: AsyncSession) -> None:
        self._product_repo = ProductRepository(session)
        self._stock_repo = StockRepository(session)
        self._session = session

    # ------------------------------------------------------------------ catalog
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

    async def list_movements(
        self, product_id: uuid.UUID, limit: int = 50, offset: int = 0
    ) -> list[StockMovement]:
        await self.get_product(product_id)
        return await self._stock_repo.list_movements(product_id, limit=limit, offset=offset)

    # ------------------------------------------------------------------ reports
    async def list_levels(self, limit: int = 100, offset: int = 0) -> list[StockLevelView]:
        rows = await self._stock_repo.list_levels_with_products(limit=limit, offset=offset)
        return [
            StockLevelView(
                product_id=product.id,
                sku=product.sku,
                name=product.name,
                category=product.category,
                quantity_on_hand=level.quantity_on_hand,
                quantity_reserved=level.quantity_reserved,
                average_cost=level.average_cost,
                reorder_level=product.reorder_level,
            )
            for product, level in rows
        ]

    async def valuation_report(self) -> ValuationReport:
        """Σ(on_hand × average_cost), with a per-category breakdown. Pure
        arithmetic over the joined product/level rows."""
        rows = await self._stock_repo.list_levels_with_products(limit=100_000, offset=0)
        by_category: dict[str, dict[str, Decimal]] = {}
        total = Decimal("0")
        for product, level in rows:
            value = (level.quantity_on_hand * level.average_cost).quantize(_CENTS)
            total += value
            bucket = by_category.setdefault(
                product.category or "uncategorized",
                {"quantity": Decimal("0"), "value": Decimal("0")},
            )
            bucket["quantity"] += level.quantity_on_hand
            bucket["value"] += value
        lines = [
            ValuationCategoryLine(category=category, quantity=vals["quantity"], value=vals["value"])
            for category, vals in sorted(by_category.items())
        ]
        return ValuationReport(total_value=total.quantize(_CENTS), categories=lines)

    async def low_stock_report(self) -> list[LowStockItem]:
        rows = await self._stock_repo.list_low_stock()
        return [
            LowStockItem(
                product_id=product.id,
                sku=product.sku,
                name=product.name,
                quantity_on_hand=on_hand,
                reorder_level=product.reorder_level,
                reorder_quantity=product.reorder_quantity,
            )
            for product, on_hand in rows
        ]

    async def cogs_for_invoice(self, invoice_id: uuid.UUID) -> Decimal:
        """Cost of goods sold for the SALE movements that reference *invoice_id*:
        Σ(quantity × weighted-average cost). The read seam finance calls to
        compute gross margin — inventory owns the numbers, finance consumes them."""
        return await self._stock_repo.cogs_for_reference("invoice", invoice_id)

    # ------------------------------------------------------------------ movements
    async def record_movement(
        self,
        product_id: uuid.UUID,
        data: InventoryMovementCreate,
        *,
        actor_id: uuid.UUID | None = None,
    ) -> StockMovement:
        """Apply a receipt/issue/sale/return. ADJUSTMENT goes through
        :meth:`adjust_stock` (it needs a reason and a signed delta)."""
        if data.movement_type == MovementType.ADJUSTMENT:
            raise UnprocessableError("Use the adjust endpoint for stock adjustments")
        signed = data.quantity if data.movement_type in INBOUND else -data.quantity
        movement, signal, recovered = await self._apply(
            product_id,
            movement_type=data.movement_type,
            quantity=data.quantity,
            signed_delta=signed,
            unit_cost=data.unit_cost,
            reason=data.reason,
            note=data.note,
            reference_type=data.reference_type,
            reference_id=data.reference_id,
            actor_id=actor_id,
        )
        await self._session.commit()
        await self._maybe_raise_low_stock(signal)
        await self._maybe_resolve_low_stock(recovered)
        return movement

    async def adjust_stock(
        self,
        product_id: uuid.UUID,
        data: StockAdjustmentCreate,
        *,
        actor_id: uuid.UUID | None = None,
    ) -> StockMovement:
        """Stock-take correction. ``quantity`` is a signed delta (may be
        negative); a reason is mandatory (invariant / separation of duties)."""
        if data.reason is None:
            raise UnprocessableError("Adjustment requires a reason")
        if data.quantity == 0:
            raise UnprocessableError("Adjustment quantity must be non-zero")
        movement, signal, recovered = await self._apply(
            product_id,
            movement_type=MovementType.ADJUSTMENT,
            quantity=abs(data.quantity),
            signed_delta=data.quantity,
            unit_cost=None,
            reason=data.reason,
            note=data.note,
            reference_type=None,
            reference_id=None,
            actor_id=actor_id,
        )
        await self._session.commit()
        await self._maybe_raise_low_stock(signal)
        await self._maybe_resolve_low_stock(recovered)
        return movement

    async def record_purchase_receipt(
        self,
        product_id: uuid.UUID,
        quantity: Decimal,
        unit_cost: Decimal,
        *,
        reference_id: uuid.UUID,
        actor_id: uuid.UUID | None = None,
    ) -> StockMovement:
        """A RECEIPT linked to a finance ``Expense``. Does **not** commit — the
        finance caller owns the transaction so the expense and the receipt land
        in one atomic commit (a crash can't book stock without the expense)."""
        movement, _, _ = await self._apply(
            product_id,
            movement_type=MovementType.RECEIPT,
            quantity=quantity,
            signed_delta=quantity,
            unit_cost=unit_cost,
            reason=MovementReason.PURCHASE,
            note=None,
            reference_type="expense",
            reference_id=reference_id,
            actor_id=actor_id,
        )
        return movement

    async def _apply(
        self,
        product_id: uuid.UUID,
        *,
        movement_type: MovementType,
        quantity: Decimal,
        signed_delta: Decimal,
        unit_cost: Decimal | None,
        reason: MovementReason | None,
        note: str | None,
        reference_type: str | None,
        reference_id: uuid.UUID | None,
        actor_id: uuid.UUID | None,
    ) -> tuple[StockMovement, _LowStockSignal | None, uuid.UUID | None]:
        """The one race-safe unit: lock the level row, guard the invariants,
        project on-hand, append the immutable ledger row, flush. Does **not**
        commit — the caller owns the transaction boundary (so it can compose with
        a finance write) and fires the post-commit low-stock alert.

        Returns ``(movement, low_stock_signal, recovered_product_id)``: the signal
        is set when this outflow crosses at/below reorder, the recovered id when an
        inflow lifts on-hand back above reorder (so the caller can auto-resolve)."""
        product = await self.get_product(product_id)
        if not product.is_active:
            raise UnprocessableError("Product is inactive")

        # SELECT ... FOR UPDATE serialises every writer for this product, so the
        # read-guard-write below is atomic (mirrors the vault-transfer lock).
        level = await self._stock_repo.get_or_create_level(product_id)
        new_on_hand = level.quantity_on_hand + signed_delta

        # Invariant: a physical outflow can never oversell. Only an explicit
        # ADJUSTMENT may drive on-hand down past what a sale/issue could.
        if new_on_hand < 0 and movement_type is not MovementType.ADJUSTMENT:
            raise UnprocessableError(
                f"Insufficient stock: on-hand {level.quantity_on_hand}, requested {quantity}"
            )
        if new_on_hand < 0:
            # The DB CheckConstraint would also reject this; fail early with a
            # clear message rather than an opaque IntegrityError.
            raise UnprocessableError(
                f"Adjustment would drive on-hand negative "
                f"({level.quantity_on_hand} + {signed_delta})"
            )

        # Weighted-average cost only moves on inbound-with-cost; an outflow leaves
        # the average untouched.
        if movement_type in INBOUND and unit_cost is not None:
            level.average_cost = _weighted_avg(
                level.quantity_on_hand, level.average_cost, quantity, unit_cost
            )

        # Point-in-time COGS: stamp the sale/issue with the weighted-average cost
        # *at the moment of the outflow*, so cost of goods sold is fixed at sale
        # time and never drifts when the product is later restocked at a new price.
        effective_unit_cost = unit_cost
        if effective_unit_cost is None and movement_type in {
            MovementType.SALE,
            MovementType.ISSUE,
        }:
            effective_unit_cost = level.average_cost

        prev_on_hand = level.quantity_on_hand
        level.quantity_on_hand = new_on_hand

        # Capture the alert transitions now (before commit expires the ORM state).
        # Low-stock fires only when an outflow crosses at/below reorder; recovery
        # fires only when an inflow lifts on-hand back strictly above it.
        signal: _LowStockSignal | None = None
        recovered_pid: uuid.UUID | None = None
        if product.reorder_level > 0:
            if signed_delta < 0 and new_on_hand <= product.reorder_level:
                signal = _LowStockSignal(
                    product_id=product.id,
                    sku=product.sku,
                    name=product.name,
                    on_hand=new_on_hand,
                    reorder_level=product.reorder_level,
                )
            elif signed_delta > 0 and prev_on_hand <= product.reorder_level < new_on_hand:
                recovered_pid = product.id

        next_sequence = await self._stock_repo.last_sequence(product_id) + 1
        movement = StockMovement(
            product_id=product_id,
            sequence=next_sequence,
            movement_type=movement_type,
            movement_reason=reason,
            quantity=quantity,
            unit_cost=effective_unit_cost,
            balance_after=new_on_hand,
            reference_type=reference_type,
            reference_id=reference_id,
            note=note,
            payload={"reason": reason.value if reason else None},
            occurred_at=datetime.now(UTC),
            created_by=actor_id,
        )
        await self._stock_repo.append_movement(movement)
        await self._stock_repo.save_level(level)
        return movement, signal, recovered_pid

    async def reconcile_low_stock_alert(self, product_id: uuid.UUID) -> None:
        """Resolve an active low-stock alert if on-hand is now above reorder. Called
        after inflows that aren't routed through :meth:`record_movement` (e.g. the
        finance stock-purchase seam), so a restock still clears the alert."""
        product = await self.get_product(product_id)
        level = await self._stock_repo.get_level(product_id)
        if level and product.reorder_level > 0 and level.quantity_on_hand > product.reorder_level:
            await self._maybe_resolve_low_stock(product_id)

    async def _maybe_raise_low_stock(self, signal: _LowStockSignal | None) -> None:
        """Best-effort low-stock alert after the movement commits. Idempotent per
        product (no duplicate while active) but *escalates* WARNING → CRITICAL when
        the product hits a hard stockout. A failure here never rolls back stock."""
        if signal is None:
            return
        stockout = signal.on_hand <= 0
        try:
            await AlertService(self._session).escalate_or_create_alert(
                AlertCreate(
                    type=AlertType.LOW_STOCK,
                    severity=AlertSeverity.CRITICAL if stockout else AlertSeverity.WARNING,
                    title=f"{'Out of stock' if stockout else 'Low stock'}: {signal.sku}",
                    body=(
                        f"{signal.name} is at {signal.on_hand} "
                        f"(reorder level {signal.reorder_level})."
                    ),
                    source_agent="inventory",
                    metadata_payload={
                        "kind": "low_stock",
                        "product_id": str(signal.product_id),
                        "sku": signal.sku,
                        "on_hand": str(signal.on_hand),
                        "reorder_level": str(signal.reorder_level),
                    },
                ),
                dedup_key=f"low_stock:{signal.product_id}",
            )
        except Exception:  # noqa: BLE001 — alerting is best-effort, never blocks stock
            logger.warning("low_stock_alert_failed", product_id=str(signal.product_id))

    async def _maybe_resolve_low_stock(self, product_id: uuid.UUID | None) -> None:
        """Best-effort: auto-resolve the active low-stock alert once stock is
        replenished above reorder, so a recovered condition doesn't linger as a
        stale active alert. Never rolls back the movement."""
        if product_id is None:
            return
        try:
            await AlertService(self._session).resolve_active_by_dedup(
                f"low_stock:{product_id}",
                note="Auto-resolved: stock replenished above reorder level.",
            )
        except Exception:  # noqa: BLE001 — alerting is best-effort, never blocks stock
            logger.warning("low_stock_resolve_failed", product_id=str(product_id))
