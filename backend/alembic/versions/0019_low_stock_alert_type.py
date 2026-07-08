"""add LOW_STOCK to the alert_type enum

Gives inventory reorder alerts a first-class alert type (instead of overloading
ANOMALY), so the alerts UI can filter/route them distinctly.

``alert_type`` is a native PostgreSQL enum whose labels are the enum *names*
(DUPLICATE_INVOICE, ANOMALY, …), so the new value is added as ``LOW_STOCK``.
``ALTER TYPE … ADD VALUE`` cannot run inside a transaction block on some
PostgreSQL versions, so it executes in an autocommit block. Idempotent — on a
fresh DB the 0001 baseline's ``create_all`` already built the type with the new
value, so ``IF NOT EXISTS`` no-ops.

Revision ID: 0019_low_stock_alert_type
Revises: 0018_inventory
Create Date: 2026-07-08 00:00:00.000000
"""

from alembic import op

revision = "0019_low_stock_alert_type"
down_revision = "0018_inventory"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE alert_type ADD VALUE IF NOT EXISTS 'LOW_STOCK'")


def downgrade() -> None:
    # NOTE: PostgreSQL cannot drop an enum value, so 'LOW_STOCK' remains on
    # alert_type (mirrors the 0004 BANK vaulttype note).
    pass
