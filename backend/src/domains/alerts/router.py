import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.domains.alerts.models import AlertStatus
from src.domains.alerts.schemas import (
    AlertCreate,
    AlertKpis,
    AlertResolve,
    AlertResponse,
)
from src.domains.alerts.service import AlertService
from src.domains.identity.dependencies import (
    RequireIntelligenceAct,
    RequireIntelligenceRead,
)
from src.infrastructure.database.postgres import get_db

router = APIRouter()

DBSession = Annotated[AsyncSession, Depends(get_db)]


@router.post("", response_model=AlertResponse, status_code=201)
async def create_alert(
    data: AlertCreate, db: DBSession, _: RequireIntelligenceAct
) -> AlertResponse:
    """Raise a new alert. The integration point for the Agent E watchdog."""
    alert = await AlertService(db).create_alert(data)
    return AlertResponse.model_validate(alert)


@router.get("", response_model=list[AlertResponse])
async def list_active_alerts(
    db: DBSession,
    _: RequireIntelligenceRead,
    limit: int = Query(default=50, ge=1, le=100),
) -> list[AlertResponse]:
    """Active (unresolved) alerts for the alerts dashboard."""
    alerts = await AlertService(db).list_alerts(AlertStatus.ACTIVE, limit=limit)
    return [AlertResponse.model_validate(a) for a in alerts]


@router.get("/resolved", response_model=list[AlertResponse])
async def list_resolved_alerts(
    db: DBSession,
    _: RequireIntelligenceRead,
    limit: int = Query(default=20, ge=1, le=100),
) -> list[AlertResponse]:
    """Recently resolved alerts."""
    alerts = await AlertService(db).list_alerts(AlertStatus.RESOLVED, limit=limit)
    return [AlertResponse.model_validate(a) for a in alerts]


@router.get("/kpis", response_model=AlertKpis)
async def alert_kpis(db: DBSession, _: RequireIntelligenceRead) -> AlertKpis:
    """Summary counts for the alert KPI cards."""
    return await AlertService(db).kpis()


@router.post("/{alert_id}/resolve", response_model=AlertResponse)
async def resolve_alert(
    alert_id: uuid.UUID,
    data: AlertResolve,
    db: DBSession,
    current_user: RequireIntelligenceAct,
) -> AlertResponse:
    """Mark an alert resolved (MANAGER+ via the intelligence-act permission)."""
    alert = await AlertService(db).resolve_alert(
        alert_id, current_user.id, data.resolution_note
    )
    return AlertResponse.model_validate(alert)
