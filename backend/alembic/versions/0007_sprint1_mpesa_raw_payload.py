"""sprint1: add raw_payload audit column to mpesa_transactions

Successful Daraja STK Push callbacks are now persisted with their full raw
envelope so the original payload is available for audit and dispute resolution
(e.g. reconciling a contested receipt against exactly what Safaricom sent).

The column is nullable so rows written before this migration — which never
captured the raw body — remain valid.

Revision ID: 0007_sprint1
Revises: 0006_sprint2
Create Date: 2026-06-12 00:00:00.000000
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0007_sprint1"
down_revision = "0006_sprint2"
branch_labels = None
depends_on = None

_TABLE_NAME = "mpesa_transactions"
_COLUMN_NAME = "raw_payload"


def upgrade() -> None:
    op.add_column(
        _TABLE_NAME,
        sa.Column(_COLUMN_NAME, sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column(_TABLE_NAME, _COLUMN_NAME)
