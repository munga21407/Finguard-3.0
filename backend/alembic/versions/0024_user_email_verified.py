"""users.email_verified_at (self-service email verification)

Adds ``email_verified_at`` to ``users``: set when the user clicks the link in
their verification email. Login requires BOTH ``is_verified`` (admin approval)
and a non-null ``email_verified_at`` (email ownership) — two independent gates.

Idempotent: the 0001 baseline's ``create_all`` reflects the current ORM, so on a
fresh database this column already exists; the add is guarded.

Revision ID: 0024_user_email_verified
Revises: 0023_user_password_changed_at
Create Date: 2026-07-09 00:00:00.000000
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0024_user_email_verified"
down_revision = "0023_user_password_changed_at"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns("users")}
    if "email_verified_at" not in cols:
        op.add_column(
            "users",
            sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
        )
    # Grandfather existing accounts: they predate email verification and could
    # already sign in, so mark them verified (backfill from created_at) rather than
    # locking everyone out on deploy. Only NULLs are touched, so re-running is safe.
    op.execute(
        "UPDATE users SET email_verified_at = created_at WHERE email_verified_at IS NULL"
    )


def downgrade() -> None:
    op.drop_column("users", "email_verified_at")
