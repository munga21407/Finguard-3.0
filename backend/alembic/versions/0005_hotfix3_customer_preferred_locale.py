"""hotfix3: add preferred_locale to customers

Agent J (Executive Summarizer) reads crm_profile["preferred_locale"] to
translate its executive bullet points into the customer's preferred language
(e.g., Swahili, Sheng).  The column was present in Agent H's data-fetch
contract but absent from the customers table, causing the localisation path
to silently fall back to English for every customer.

Column spec:
  - VARCHAR(50), nullable — existing rows receive NULL (Python fallback → "en")
  - No backfill required; Agent J already guards: preferred_locale or "en"

Revision ID: 0005_hotfix3
Revises: 0004_sprint4
Create Date: 2026-06-04 00:00:00.000000
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005_hotfix3"
down_revision = "0004_sprint4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "customers",
        sa.Column("preferred_locale", sa.String(50), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("customers", "preferred_locale")
