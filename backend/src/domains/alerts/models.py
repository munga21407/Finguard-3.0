import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.database.postgres import Base


class AlertType(enum.StrEnum):
    DUPLICATE_INVOICE = "duplicate_invoice"
    ANOMALY = "anomaly"
    VENDOR_ACTIVITY = "vendor_activity"
    BUDGET_OVERSPEND = "budget_overspend"
    LOW_STOCK = "low_stock"


class AlertSeverity(enum.StrEnum):
    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"


class AlertStatus(enum.StrEnum):
    ACTIVE = "active"
    RESOLVED = "resolved"


class Alert(Base):
    """A finance/compliance alert raised by an agent (typically Agent E).

    Read by the alerts dashboard widgets; created via POST /alerts (the
    integration point for the watchdog) and closed via POST /alerts/{id}/resolve.
    """

    __tablename__ = "alerts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    type: Mapped[AlertType] = mapped_column(Enum(AlertType, name="alert_type"), nullable=False)
    severity: Mapped[AlertSeverity] = mapped_column(
        Enum(AlertSeverity, name="alert_severity"), nullable=False
    )
    status: Mapped[AlertStatus] = mapped_column(
        Enum(AlertStatus, name="alert_status"),
        default=AlertStatus.ACTIVE,
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    source_agent: Mapped[str | None] = mapped_column(String(100), nullable=True)
    vc_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    metadata_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
