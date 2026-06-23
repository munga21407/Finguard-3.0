"""Watchdog-result → AlertCreate mapping (hermetic, no DB).

The watchdog consumer turns an Agent E analysis dict into an alert via
``alert_from_watchdog``; the mapping precedence and severity are pure, so they
are unit-tested here.
"""
from __future__ import annotations

from src.domains.alerts.models import AlertSeverity, AlertType
from src.domains.alerts.service import alert_from_watchdog


def _analysis(**overrides: object) -> dict:
    base = {
        "account_id": "acct-1",
        "current_state": "HEALTHY",
        "anomaly_detected": False,
        "anomaly_score": 0.1,
        "isolation_score": 0.1,
        "is_duplicate": False,
        "duplicate_match_score": 0.0,
        "vc_id": "vc-123",
    }
    base.update(overrides)
    return base


def test_benign_result_raises_no_alert() -> None:
    assert alert_from_watchdog(_analysis(), "exp-1") is None


def test_duplicate_takes_precedence_over_everything() -> None:
    out = alert_from_watchdog(
        _analysis(
            is_duplicate=True,
            duplicate_match_score=0.93,
            anomaly_detected=True,
            isolation_score=0.95,
        ),
        "exp-1",
    )
    assert out is not None
    assert out.type == AlertType.DUPLICATE_INVOICE
    assert "93%" in out.body
    assert out.metadata_payload["expense_id"] == "exp-1"


def test_critical_state_maps_to_overspend_critical() -> None:
    out = alert_from_watchdog(
        _analysis(current_state="CRITICAL", anomaly_detected=True, anomaly_score=0.8),
        "exp-2",
    )
    assert out is not None
    assert out.type == AlertType.BUDGET_OVERSPEND
    assert out.severity == AlertSeverity.CRITICAL
    assert out.source_agent == "E"
    assert out.vc_id == "vc-123"


def test_high_isolation_only_maps_to_anomaly() -> None:
    out = alert_from_watchdog(_analysis(isolation_score=0.72), "exp-3")
    assert out is not None
    assert out.type == AlertType.ANOMALY
    # 0.72 is over the alert threshold but under the critical cutoff → warning.
    assert out.severity == AlertSeverity.WARNING


def test_very_high_isolation_is_critical() -> None:
    out = alert_from_watchdog(_analysis(isolation_score=0.9), "exp-4")
    assert out is not None
    assert out.severity == AlertSeverity.CRITICAL


def test_isolation_below_threshold_is_not_alerted() -> None:
    assert alert_from_watchdog(_analysis(isolation_score=0.5), "exp-5") is None
