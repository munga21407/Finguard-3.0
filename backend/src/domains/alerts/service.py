from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import NotFoundError
from src.domains.alerts.models import Alert, AlertSeverity, AlertStatus, AlertType
from src.domains.alerts.schemas import AlertCreate, AlertKpis

# Key under which a de-duplication token is stored in ``metadata_payload`` so a
# repeatedly-detected condition (e.g. the same expense re-processed) raises at
# most one active alert.
DEDUP_KEY = "dedup_key"

# Above this IsolationForest score a transaction is anomalous enough to alert on
# even when the HMM budget state is not yet CRITICAL.  Mirrors the threshold the
# watchdog agent uses to decide whether to publish an anomaly event.
_ISOLATION_ALERT_THRESHOLD = 0.7


def alert_from_watchdog(analysis: dict[str, Any], expense_id: str) -> AlertCreate | None:
    """Map an Agent E watchdog result into an ``AlertCreate`` (pure / DB-free).

    Returns ``None`` when nothing rises to the level of an alert, so the caller
    only persists a row when there is something a human should look at.  The
    type/severity precedence is: a detected duplicate is the most actionable,
    then a CRITICAL budget state (overspend), then a high IsolationForest score.
    """
    is_duplicate = bool(analysis.get("is_duplicate"))
    anomaly_detected = bool(analysis.get("anomaly_detected"))
    isolation_score = float(analysis.get("isolation_score") or 0.0)
    anomaly_score = float(analysis.get("anomaly_score") or 0.0)
    current_state = str(analysis.get("current_state") or "")
    account_id = str(analysis.get("account_id") or "")
    vc_id = analysis.get("vc_id")

    high_isolation = isolation_score >= _ISOLATION_ALERT_THRESHOLD
    if not (is_duplicate or anomaly_detected or high_isolation):
        return None

    if is_duplicate:
        alert_type = AlertType.DUPLICATE_INVOICE
        match_pct = float(analysis.get("duplicate_match_score") or 0.0) * 100
        title = "Possible duplicate invoice detected"
        body = (
            f"Agent E flagged a likely duplicate for expense {expense_id} "
            f"(fuzzy match {match_pct:.0f}%). Review before payment."
        )
    elif anomaly_detected:
        alert_type = AlertType.BUDGET_OVERSPEND
        title = "Budget watchdog: CRITICAL spending state"
        body = (
            f"Account {account_id} is in a CRITICAL budget state "
            f"(weighted anomaly score {anomaly_score:.2f}) after expense {expense_id}."
        )
    else:
        alert_type = AlertType.ANOMALY
        title = "Anomalous transaction amount detected"
        body = (
            f"Expense {expense_id} scored {isolation_score:.2f} on the "
            f"IsolationForest outlier model — well outside the normal range."
        )

    # CRITICAL state or a very strong outlier signal is critical; otherwise warn.
    severity = (
        AlertSeverity.CRITICAL
        if (anomaly_detected or isolation_score >= 0.85)
        else AlertSeverity.WARNING
    )

    return AlertCreate(
        type=alert_type,
        severity=severity,
        title=title,
        body=body,
        source_agent="E",
        vc_id=str(vc_id) if vc_id else None,
        metadata_payload={
            "expense_id": expense_id,
            "account_id": account_id,
            "current_state": current_state,
            "anomaly_score": anomaly_score,
            "isolation_score": isolation_score,
            "is_duplicate": is_duplicate,
            "duplicate_match_score": float(analysis.get("duplicate_match_score") or 0.0),
        },
    )


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

    async def create_alert_idempotent(
        self, data: AlertCreate, dedup_key: str
    ) -> Alert | None:
        """Create an alert unless an *active* one already carries ``dedup_key``.

        Returns the new ``Alert`` when one was created, or ``None`` when an
        active alert with the same key already exists.  Used by the watchdog
        consumer so a re-processed expense never spawns duplicate alerts.
        """
        existing = await self._session.execute(
            select(Alert.id)
            .where(Alert.status == AlertStatus.ACTIVE)
            .where(Alert.metadata_payload[DEDUP_KEY].astext == dedup_key)
            .limit(1)
        )
        if existing.first() is not None:
            return None

        payload = dict(data.metadata_payload)
        payload[DEDUP_KEY] = dedup_key
        alert = Alert(**{**data.model_dump(), "metadata_payload": payload})
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
