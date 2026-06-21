"""vault_transfers — internal treasury movements between vaults

Adds the ``vault_transfers`` table backing per-vault balances and the "move money"
action.  A transfer is net-zero to total cash; an optional fee is booked as a
separate Expense (vault = source) linked via ``fee_expense_id``.  The ``vaulttype``
enum already exists (added in 0004), so the enum columns reuse it.

Revision ID: 0005_vault_transfers
Revises: 0004_payment_links_and_bank_rail
Create Date: 2026-06-21 00:00:00.000000
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0005_vault_transfers"
down_revision = "0004_payment_links_and_bank_rail"
branch_labels = None
depends_on = None

# Reference the existing enum without re-creating it.
_VAULT = postgresql.ENUM("MPESA", "CASH", "BANK", name="vaulttype", create_type=False)


def upgrade() -> None:
    op.create_table(
        "vault_transfers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("from_vault", _VAULT, nullable=False),
        sa.Column("to_vault", _VAULT, nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("fee", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("reference_note", sa.Text(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "fee_expense_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("expenses.id"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("from_vault <> to_vault", name="ck_vault_transfers_distinct_vaults"),
    )


def downgrade() -> None:
    op.drop_table("vault_transfers")
