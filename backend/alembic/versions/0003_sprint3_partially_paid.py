"""sprint3: add partially_paid to invoicestatus enum

Revision ID: 0003_sprint3
Revises: 0002_sprint2
Create Date: 2026-06-03 00:00:00.000000
"""
from __future__ import annotations

from alembic import op

revision = "0003_sprint3"
down_revision = "0002_sprint2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # PostgreSQL ENUM types cannot be altered inside a transaction.
    # op.execute runs in autocommit mode when the connection is set to
    # AUTOCOMMIT, but Alembic batches DDL by default; we use the
    # standard ALTER TYPE … ADD VALUE approach which is safe for adding
    # a new value (it is idempotent when guarded by IF NOT EXISTS).
    op.execute("ALTER TYPE invoicestatus ADD VALUE IF NOT EXISTS 'partially_paid'")


def downgrade() -> None:
    # PostgreSQL does not support removing enum values without recreating the type.
    # Provide a no-op downgrade — the value is harmless when not referenced.
    pass
