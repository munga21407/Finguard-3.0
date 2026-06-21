from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from src.domains.alerts.models import AlertSeverity, AlertStatus, AlertType


class AlertCreate(BaseModel):
    type: AlertType
    severity: AlertSeverity
    title: str = Field(..., max_length=255)
    body: str
    source_agent: str | None = None
    vc_id: str | None = None
    metadata_payload: dict[str, Any] = Field(default_factory=dict)


class AlertResolve(BaseModel):
    resolution_note: str | None = None


class AlertResponse(BaseModel):
    id: uuid.UUID
    type: AlertType
    severity: AlertSeverity
    status: AlertStatus
    title: str
    body: str
    source_agent: str | None
    vc_id: str | None
    metadata_payload: dict[str, Any]
    resolved_by: uuid.UUID | None
    resolved_at: datetime | None
    resolution_note: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class AlertKpis(BaseModel):
    """Summary counts for the AlertKpiCards widget."""
    active: int
    critical: int
    resolved_last_7d: int
    avg_resolution_hours: float | None
