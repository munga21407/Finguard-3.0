"""Deterministic unit tests for Agent G (Credit Strategist) numeric core.

``_forecast_series`` (Holt-Winters with graceful fallbacks) and the
``_compute_bankability_score`` rubric are pure — no LLM, no DB. These pin the
non-negativity guarantee, the small-sample fallback, and the score/tier rubric.
"""
from __future__ import annotations

from src.domains.intelligence.agents.g_reporter import (
    _compute_bankability_score,
    _forecast_series,
)

# ── _forecast_series ──────────────────────────────────────────────────────────

def test_forecast_empty_history_is_zeros() -> None:
    assert _forecast_series([], periods=12) == [0.0] * 12


def test_forecast_small_sample_linear_extrapolation() -> None:
    # n < 4 → mean (11) + slope (2) * (i+1): 13, 15, 17
    assert _forecast_series([10.0, 12.0], periods=3) == [13.0, 15.0, 17.0]


def test_forecast_never_negative() -> None:
    out = _forecast_series([10.0, 2.0], periods=5)  # steep negative slope
    assert len(out) == 5
    assert all(v >= 0.0 for v in out)


def test_forecast_holtwinters_branch_shape() -> None:
    out = _forecast_series([100.0, 110.0, 120.0, 130.0], periods=4)
    assert len(out) == 4
    assert all(v >= 0.0 for v in out)


# ── _compute_bankability_score ────────────────────────────────────────────────

def test_bankability_healthy_company_scores_low_risk() -> None:
    total, tier, sub = _compute_bankability_score(
        hist_revenue=[100.0, 110.0, 130.0],
        hist_opex=[40.0, 42.0, 45.0],
        fc_revenue=[140.0, 150.0, 160.0, 170.0],
        fc_opex=[50.0, 55.0, 60.0, 65.0],
    )
    assert 0 <= total <= 100
    assert total >= 75
    assert tier == "LOW"
    assert set(sub) == {"trend_score", "ratio_score", "consistency_score", "runway_score"}


def test_bankability_distressed_company_scores_high_risk() -> None:
    total, tier, _ = _compute_bankability_score(
        hist_revenue=[100.0, 90.0, 80.0],     # declining
        hist_opex=[110.0, 115.0, 120.0],      # opex above revenue
        fc_revenue=[70.0, 60.0],
        fc_opex=[120.0, 130.0],               # insolvent forecast
    )
    assert total < 45
    assert tier == "HIGH"
