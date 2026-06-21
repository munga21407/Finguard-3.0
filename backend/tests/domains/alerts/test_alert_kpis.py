"""Alert KPI aggregation (hermetic, no DB).

GET /alerts/kpis serves these; the aggregation is pure so it is unit-tested here.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from src.domains.alerts.models import Alert, AlertSeverity, AlertStatus, AlertType
from src.domains.alerts.service import compute_kpis

_NOW = datetime(2026, 6, 21, 12, tzinfo=UTC)


def _alert(
    *,
    status: AlertStatus,
    severity: AlertSeverity = AlertSeverity.WARNING,
    created: datetime | None = None,
    resolved: datetime | None = None,
) -> Alert:
    return Alert(
        id=uuid.uuid4(),
        type=AlertType.ANOMALY,
        severity=severity,
        status=status,
        title="t",
        body="b",
        metadata_payload={},
        created_at=created or _NOW,
        resolved_at=resolved,
    )


def test_counts_active_and_critical() -> None:
    alerts = [
        _alert(status=AlertStatus.ACTIVE, severity=AlertSeverity.CRITICAL),
        _alert(status=AlertStatus.ACTIVE, severity=AlertSeverity.WARNING),
        _alert(status=AlertStatus.RESOLVED, resolved=_NOW),
    ]
    kpis = compute_kpis(alerts, _NOW)
    assert kpis.active == 2
    assert kpis.critical == 1


def test_resolved_last_7d_window() -> None:
    alerts = [
        _alert(status=AlertStatus.RESOLVED, created=_NOW - timedelta(days=10), resolved=_NOW - timedelta(days=2)),
        _alert(status=AlertStatus.RESOLVED, created=_NOW - timedelta(days=30), resolved=_NOW - timedelta(days=10)),
    ]
    kpis = compute_kpis(alerts, _NOW)
    assert kpis.resolved_last_7d == 1


def test_avg_resolution_hours() -> None:
    alerts = [
        _alert(status=AlertStatus.RESOLVED, created=_NOW - timedelta(hours=4), resolved=_NOW),
        _alert(status=AlertStatus.RESOLVED, created=_NOW - timedelta(hours=2), resolved=_NOW),
    ]
    kpis = compute_kpis(alerts, _NOW)
    assert kpis.avg_resolution_hours == 3.0


def test_avg_resolution_none_when_no_resolved() -> None:
    kpis = compute_kpis([_alert(status=AlertStatus.ACTIVE)], _NOW)
    assert kpis.avg_resolution_hours is None
