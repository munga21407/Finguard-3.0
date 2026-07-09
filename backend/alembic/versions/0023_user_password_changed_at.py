"""users.password_changed_at (password-reset session invalidation)

Adds ``password_changed_at`` to ``users``. It is set on every password reset;
authentication rejects any access/refresh token whose ``iat`` predates it, so a
reset immediately invalidates existing sessions (including a stolen refresh
token). NULL for accounts that have never reset — those tokens are unaffected.

Idempotent: the 0001 baseline's ``create_all`` reflects the current ORM, so on a
fresh database this column already exists; the add is guarded.

Revision ID: 0023_user_password_changed_at
Revises: 0022_email_opt_outs
Create Date: 2026-07-09 00:00:00.000000
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0023_user_password_changed_at"
down_revision = "0022_email_opt_outs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    cols = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("users")}
    if "password_changed_at" not in cols:
        op.add_column(
            "users",
            sa.Column("password_changed_at", sa.DateTime(timezone=True), nullable=True),
        )


def downgrade() -> None:
    op.drop_column("users", "password_changed_at")
