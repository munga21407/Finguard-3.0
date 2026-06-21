from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import NotFoundError
from src.domains.alerts.models import Alert, AlertSeverity, AlertStatus
from src.domains.alerts.schemas import AlertCreate, AlertKpis


def compute_kpis(alerts: list[Alert], now: datetime) -> AlertKpis:
    """Pure KPI aggregation over a list of alerts (DB-free for unit testing)."""
    week_ago = now - timedelta(days=7)

    active = [a for a in alerts if a.status == AlertStatus.ACTIVE]
    resolved_7d = [
        a
        for a in alerts
        if a.status == AlertStatus.RESOLVED
        and a.resolved_at is not None
        and a.resolved_at >= week_ago
    ]
    durations = [
        (a.resolved_at - a.created_at).total_seconds() / 3600
        for a in alerts
        if a.status == AlertStatus.RESOLVED and a.resolved_at is not None
    ]

    return AlertKpis(
        active=len(active),
        critical=sum(1 for a in active if a.severity == AlertSeverity.CRITICAL),
        resolved_last_7d=len(resolved_7d),
        avg_resolution_hours=(sum(durations) / len(durations)) if durations else None,
    )


class AlertService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_alert(self, data: AlertCreate) -> Alert:
        alert = Alert(**data.model_dump())
        self._session.add(alert)
        await self._session.commit()
        await self._session.refresh(alert)
        return alert

    async def list_alerts(self, status: AlertStatus, limit: int = 50) -> list[Alert]:
        stmt = (
            select(Alert)
            .where(Alert.status == status)
            .order_by(Alert.created_at.desc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def resolve_alert(
        self,
        alert_id: uuid.UUID,
        resolved_by: uuid.UUID,
        resolution_note: str | None,
    ) -> Alert:
        alert = await self._session.get(Alert, alert_id)
        if alert is None:
            raise NotFoundError("Alert not found")
        alert.status = AlertStatus.RESOLVED
        alert.resolved_by = resolved_by
        alert.resolved_at = datetime.now(UTC)
        alert.resolution_note = resolution_note
        await self._session.commit()
        await self._session.refresh(alert)
        return alert

    async def kpis(self) -> AlertKpis:
        result = await self._session.execute(select(Alert))
        return compute_kpis(list(result.scalars().all()), datetime.now(UTC))
