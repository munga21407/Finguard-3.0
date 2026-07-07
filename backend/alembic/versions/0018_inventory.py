from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0018_inventory"
down_revision = "0017_settlement_idempotency"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "products",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sku", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("unit", sa.String(length=20), nullable=False),
        sa.Column("category", sa.String(length=100), nullable=True),
        sa.Column("cost_price", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("selling_price", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("reorder_level", sa.Numeric(precision=18, scale=3), nullable=False),
        sa.Column("reorder_quantity", sa.Numeric(precision=18, scale=3), nullable=False),
        sa.Column("barcode", sa.String(length=64), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("sku", name="uq_products_sku"),
    )
    op.create_index(op.f("ix_products_barcode"), "products", ["barcode"], unique=False)
    op.create_index(op.f("ix_products_category"), "products", ["category"], unique=False)
    op.create_index(op.f("ix_products_sku"), "products", ["sku"], unique=False)

    op.create_table(
        "stock_levels",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("location_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("quantity_on_hand", sa.Numeric(precision=18, scale=3), nullable=False),
        sa.Column("quantity_reserved", sa.Numeric(precision=18, scale=3), nullable=False),
        sa.Column("average_cost", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], name="fk_stock_levels_product_id_products"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("product_id", "location_id", name="uq_stock_levels_product_location"),
        sa.CheckConstraint("quantity_on_hand >= 0", name="ck_stock_levels_nonneg_on_hand"),
        sa.CheckConstraint("quantity_reserved >= 0", name="ck_stock_levels_nonneg_reserved"),
    )
    op.create_index(op.f("ix_stock_levels_product_id"), "stock_levels", ["product_id"], unique=False)

    op.create_table(
        "stock_movements",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("movement_type", sa.String(length=20), nullable=False),
        sa.Column("movement_reason", sa.String(length=20), nullable=True),
        sa.Column("quantity", sa.Numeric(precision=18, scale=3), nullable=False),
        sa.Column("unit_cost", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], name="fk_stock_movements_product_id_products"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("product_id", "sequence", name="uq_stock_movements_product_sequence"),
    )
    op.create_index(op.f("ix_stock_movements_product_id"), "stock_movements", ["product_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_stock_movements_product_id"), table_name="stock_movements")
    op.drop_table("stock_movements")
    op.drop_index(op.f("ix_stock_levels_product_id"), table_name="stock_levels")
    op.drop_table("stock_levels")
    op.drop_index(op.f("ix_products_sku"), table_name="products")
    op.drop_index(op.f("ix_products_category"), table_name="products")
    op.drop_index(op.f("ix_products_barcode"), table_name="products")
    op.drop_table("products")
