import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.domains.inventory.types import MovementReason, MovementType, UnitOfMeasure
from src.infrastructure.database.postgres import Base


class Product(Base):
    __tablename__ = "products"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    sku: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    unit: Mapped[UnitOfMeasure] = mapped_column(
        Enum(UnitOfMeasure, native_enum=False, length=20),
        default=UnitOfMeasure.EACH,
        nullable=False,
    )
    category: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    cost_price: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, default=Decimal("0")
    )
    selling_price: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, default=Decimal("0")
    )
    reorder_level: Mapped[Decimal] = mapped_column(
        Numeric(18, 3), nullable=False, default=Decimal("0")
    )
    reorder_quantity: Mapped[Decimal] = mapped_column(
        Numeric(18, 3), nullable=False, default=Decimal("0")
    )
    barcode: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )


class StockLevel(Base):
    __tablename__ = "stock_levels"
    __table_args__ = (
        UniqueConstraint("product_id", "location_id", name="uq_stock_levels_product_location"),
        CheckConstraint("quantity_on_hand >= 0", name="ck_stock_levels_nonneg_on_hand"),
        CheckConstraint("quantity_reserved >= 0", name="ck_stock_levels_nonneg_reserved"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id"), nullable=False, index=True
    )
    location_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    quantity_on_hand: Mapped[Decimal] = mapped_column(
        Numeric(18, 3), nullable=False, default=Decimal("0")
    )
    quantity_reserved: Mapped[Decimal] = mapped_column(
        Numeric(18, 3), nullable=False, default=Decimal("0")
    )
    average_cost: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, default=Decimal("0")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )


class StockMovement(Base):
    __tablename__ = "stock_movements"
    __table_args__ = (
        UniqueConstraint("product_id", "sequence", name="uq_stock_movements_product_sequence"),
        CheckConstraint("quantity > 0", name="ck_stock_movements_positive_qty"),
        Index("ix_stock_movements_reference", "reference_type", "reference_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id"), nullable=False, index=True
    )
    sequence: Mapped[int] = mapped_column(nullable=False)
    movement_type: Mapped[MovementType] = mapped_column(
        Enum(MovementType, native_enum=False, length=20), nullable=False
    )
    movement_reason: Mapped[MovementReason | None] = mapped_column(
        Enum(MovementReason, native_enum=False, length=20), nullable=True
    )
    # Always positive; the signed direction is derived from ``movement_type`` (and,
    # for ADJUSTMENT, recorded via ``balance_after`` so the ledger stays replayable).
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 3), nullable=False)
    unit_cost: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    # On-hand snapshot immediately after applying this movement (audit/debug + fold).
    balance_after: Mapped[Decimal] = mapped_column(Numeric(18, 3), nullable=False)
    # Link back to the finance object that drove this movement (never the model
    # itself — inventory stores only the reference, keeping the dependency one-way).
    reference_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    reference_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
