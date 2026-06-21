"""alerts table — agent-raised finance/compliance alerts

Adds the ``alerts`` table backing the alerts dashboard widgets (KPI cards,
active/resolved lists). The ``0001_initial`` baseline does not include this
table — its ``create_all`` runs over an explicit module list that predates the
alerts domain — so this revision creates the table (and its three enum types)
directly. Enum values are the member *names* to match SQLAlchemy's default
native-enum behaviour used elsewhere in the schema.

Revision ID: 0003_alerts
Revises: 0002_invoice_events
Create Date: 2026-06-21 00:00:00.000000
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003_alerts"
down_revision = "0002_invoice_events"
branch_labels = None
depends_on = None

_ALERT_TYPE = sa.Enum(
    "DUPLICATE_INVOICE", "ANOMALY", "VENDOR_ACTIVITY", "BUDGET_OVERSPEND", name="alert_type"
)
_ALERT_SEVERITY = sa.Enum("CRITICAL", "WARNING", "INFO", name="alert_severity")
_ALERT_STATUS = sa.Enum("ACTIVE", "RESOLVED", name="alert_status")


def upgrade() -> None:
    op.create_table(
        "alerts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("type", _ALERT_TYPE, nullable=False),
        sa.Column("severity", _ALERT_SEVERITY, nullable=False),
        sa.Column("status", _ALERT_STATUS, nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("source_agent", sa.String(100), nullable=True),
        sa.Column("vc_id", sa.String(255), nullable=True),
        sa.Column("metadata_payload", postgresql.JSONB(), nullable=False),
        sa.Column("resolved_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_alerts_status", "alerts", ["status"])
    op.create_index("ix_alerts_created_at", "alerts", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_alerts_created_at", table_name="alerts")
    op.drop_index("ix_alerts_status", table_name="alerts")
    op.drop_table("alerts")
    _ALERT_STATUS.drop(op.get_bind(), checkfirst=True)
    _ALERT_SEVERITY.drop(op.get_bind(), checkfirst=True)
    _ALERT_TYPE.drop(op.get_bind(), checkfirst=True)
