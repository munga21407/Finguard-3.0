"""Deterministic unit tests for Agent D (Forecaster) cash-runway estimation.

``_estimate_runway`` is pure arithmetic over a balance + daily flow forecast —
the rest of the agent (Holt-Winters fit, Text-to-SQL CoVe) needs statsmodels/LLM.
These pin the three branches: depletion within the horizon, a surplus horizon,
and negative-drift extrapolation beyond it.
"""
from __future__ import annotations

from src.domains.intelligence.services.forecast_service import _estimate_runway


def test_runway_depletes_within_horizon_days() -> None:
    # 100 balance, -25/day → hits zero on day 4.
    assert _estimate_runway(100.0, [-25.0, -25.0, -25.0, -25.0]) == "4 Days"


def test_runway_depletion_past_60_days_reported_in_months() -> None:
    # 1000 balance, -10/day over a 100-day forecast → zero on day 100 → "3 Months".
    flows = [-10.0] * 100
    assert _estimate_runway(1000.0, flows) == "3 Months"


def test_runway_positive_drift_stays_above_zero() -> None:
    # Net-positive flows never deplete within the horizon.
    assert _estimate_runway(500.0, [10.0, 20.0, 5.0]) == ">30 Days"


def test_runway_negative_drift_extrapolated_beyond_horizon() -> None:
    # Survives the 3-day window but avg flow is negative → extrapolate.
    # balance ends 500-3=497 after [-1,-1,-1]; avg=-1 → extra≈497 days → Months.
    result = _estimate_runway(500.0, [-1.0, -1.0, -1.0])
    assert result.endswith("Months")
