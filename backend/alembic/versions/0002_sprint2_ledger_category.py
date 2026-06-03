"""sprint2: add category column to ledger_entries

Revision ID: 0002_sprint2
Revises: 0001_sprint1
Create Date: 2026-06-03 00:00:00.000000
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002_sprint2"
down_revision = "0001_sprint1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ledger_entries",
        sa.Column("category", sa.String(100), nullable=True),
    )
    op.create_index(
        "ix_ledger_entries_category",
        "ledger_entries",
        ["category"],
    )


def downgrade() -> None:
    op.drop_index("ix_ledger_entries_category", table_name="ledger_entries")
    op.drop_column("ledger_entries", "category")
