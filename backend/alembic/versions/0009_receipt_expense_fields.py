"""receipt scanner: add OCR provenance columns to expenses

The Receipt Scanner (POST /finance/receipts) persists an expense from an OCR'd
receipt.  These nullable columns retain the extracted audit trail:

  * merchant_name — vendor printed on the receipt
  * kra_pin       — KRA PIN, used by Agent F for tax-compliance checks
  * description   — free-text note / reference
  * receipt_date  — printed transaction date (may differ from created_at)

All nullable so rows written before this migration remain valid.

Revision ID: 0009_receipt
Revises: 0008_sprint2
Create Date: 2026-06-13 00:00:00.000000
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0009_receipt"
down_revision = "0008_sprint2"
branch_labels = None
depends_on = None

_TABLE = "expenses"
_COLUMN_NAMES = ("merchant_name", "kra_pin", "description", "receipt_date")


def upgrade() -> None:
    op.add_column(_TABLE, sa.Column("merchant_name", sa.String(length=255), nullable=True))
    op.add_column(_TABLE, sa.Column("kra_pin", sa.String(length=20), nullable=True))
    op.add_column(_TABLE, sa.Column("description", sa.Text(), nullable=True))
    op.add_column(_TABLE, sa.Column("receipt_date", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    for name in reversed(_COLUMN_NAMES):
        op.drop_column(_TABLE, name)
