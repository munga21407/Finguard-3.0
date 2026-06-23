from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from src.domains.audit.models import AuditActorType, AuditOutcome


class AuditLogResponse(BaseModel):
    id: uuid.UUID
    actor_type: AuditActorType
    actor_id: uuid.UUID | None
    actor_label: str | None
    action: str
    resource_type: str
    resource_id: str | None
    outcome: AuditOutcome
    ip_address: str | None
    request_id: str | None
    metadata_payload: dict[str, Any]
    created_at: datetime

    model_config = {"from_attributes": True}


class AuditLogPage(BaseModel):
    """A page of audit entries plus the total matching the filter (for paging)."""

    items: list[AuditLogResponse]
    total: int
    limit: int
    offset: int


class AuditKpis(BaseModel):
    """Summary counts for the activity-log dashboard cards."""

    total: int
    last_24h: int
    failures_last_24h: int
    denied_last_24h: int
