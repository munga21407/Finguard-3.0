"""sprint2: verify pre-existing active users

Login now requires ``is_verified = true``.  Accounts created before this change
defaulted to ``is_verified = false``; without a backfill every current user
would be locked out on deploy.  Mark all existing *active* users as verified so
they retain access, while new self-registrations still follow the
verify-before-login flow (only the first-ever user bootstraps verified).

This is a one-way data backfill; ``downgrade`` is intentionally a no-op because
re-unverifying users would lock them out and we cannot know which rows were
unverified beforehand.

Revision ID: 0008_sprint2
Revises: 0007_sprint1
Create Date: 2026-06-13 00:00:00.000000
"""
from __future__ import annotations

from alembic import op

revision = "0008_sprint2"
down_revision = "0007_sprint1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE users SET is_verified = true WHERE is_active = true")


def downgrade() -> None:
    # No-op: re-unverifying users would lock them out and the prior state is
    # not recoverable.
    pass
