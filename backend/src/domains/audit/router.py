import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import NotFoundError
from src.domains.audit.models import AuditLog, AuditOutcome
from src.domains.audit.schemas import AuditKpis, AuditLogPage, AuditLogResponse
from src.domains.audit.service import AuditService
from src.domains.identity.dependencies import RequireAuditRead
from src.infrastructure.database.postgres import get_db

router = APIRouter()

DBSession = Annotated[AsyncSession, Depends(get_db)]


@router.get("", response_model=AuditLogPage)
async def list_audit_logs(
    db: DBSession,
    _: RequireAuditRead,
    actor_id: uuid.UUID | None = None,
    action: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    outcome: AuditOutcome | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> AuditLogPage:
    """Filtered, paginated, most-recent-first activity trail (managers+)."""
    items, total = await AuditService(db).query(
        actor_id=actor_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        outcome=outcome,
        since=since,
        until=until,
        limit=limit,
        offset=offset,
    )
    return AuditLogPage(
        items=[AuditLogResponse.model_validate(i) for i in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/kpis", response_model=AuditKpis)
async def audit_kpis(db: DBSession, _: RequireAuditRead) -> AuditKpis:
    """Summary counts for the activity-log dashboard cards."""
    return await AuditService(db).kpis()


@router.get("/{audit_id}", response_model=AuditLogResponse)
async def get_audit_log(
    audit_id: uuid.UUID, db: DBSession, _: RequireAuditRead
) -> AuditLogResponse:
    """A single audit entry (full metadata payload) by id."""
    entry = await db.get(AuditLog, audit_id)
    if entry is None:
        raise NotFoundError("Audit entry not found")
    return AuditLogResponse.model_validate(entry)
