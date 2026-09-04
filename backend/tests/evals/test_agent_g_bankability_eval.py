"""Agent G — deterministic bankability calibration (blocks CI; no LLM, no DB).

The bankability score is computed in pure Python (``_compute_bankability_score``);
the LLM only writes prose. So the score is pinned against **immutable labeled
profiles** — a healthy, a moderate, and a distressed SME — asserting tier
assignment, monotonic ordering, and bounds. This is the stable baseline for
tuning ``BankabilityTuning`` (weights / tier cutoffs) without silent drift.
"""
from __future__ import annotations

from src.domains.intelligence.services.bankability_service import _compute_bankability_score

# ── Immutable labeled profiles (monthly KES, oldest-first) ────────────────────
# Healthy: strong revenue growth, opex ~40% of revenue, consistent, solvent.
HEALTHY_REV = [80_000, 95_000, 110_000, 130_000, 150_000, 175_000]
HEALTHY_OPX = [32_000, 38_000, 44_000, 50_000, 56_000, 62_000]
HEALTHY_FC_REV = [180_000, 190_000, 200_000, 210_000]
HEALTHY_FC_OPX = [64_000, 66_000, 68_000, 70_000]

# Moderate: flat revenue, opex ~70% of revenue, steady, just solvent.
MODERATE_REV = [100_000] * 6
MODERATE_OPX = [70_000] * 6
MODERATE_FC_REV = [100_000] * 4
MODERATE_FC_OPX = [70_000] * 4

# Distressed: declining revenue, opex ≥ revenue, volatile, insolvent forecast.
DISTRESSED_REV = [150_000, 140_000, 120_000, 100_000, 80_000, 60_000]
DISTRESSED_OPX = [140_000, 145_000, 140_000, 150_000, 145_000, 150_000]
DISTRESSED_FC_REV = [55_000, 50_000, 45_000, 40_000]
DISTRESSED_FC_OPX = [140_000, 140_000, 140_000, 140_000]


def _score(rev, opx, fc_rev, fc_opx) -> tuple[int, str]:
    total, tier, _sub = _compute_bankability_score(rev, opx, fc_rev, fc_opx)
    return total, tier


def test_healthy_profile_is_low_risk() -> None:
    score, tier = _score(HEALTHY_REV, HEALTHY_OPX, HEALTHY_FC_REV, HEALTHY_FC_OPX)
    assert tier == "LOW"
    assert score >= 75


def test_moderate_profile_is_medium_risk() -> None:
    score, tier = _score(MODERATE_REV, MODERATE_OPX, MODERATE_FC_REV, MODERATE_FC_OPX)
    assert tier == "MEDIUM"
    assert 45 <= score < 75


def test_distressed_profile_is_high_risk() -> None:
    score, tier = _score(DISTRESSED_REV, DISTRESSED_OPX, DISTRESSED_FC_REV, DISTRESSED_FC_OPX)
    assert tier == "HIGH"
    assert score < 45


def test_scores_are_monotonic_and_bounded() -> None:
    healthy, _ = _score(HEALTHY_REV, HEALTHY_OPX, HEALTHY_FC_REV, HEALTHY_FC_OPX)
    moderate, _ = _score(MODERATE_REV, MODERATE_OPX, MODERATE_FC_REV, MODERATE_FC_OPX)
    distressed, _ = _score(DISTRESSED_REV, DISTRESSED_OPX, DISTRESSED_FC_REV, DISTRESSED_FC_OPX)
    assert healthy > moderate > distressed
    for s in (healthy, moderate, distressed):
        assert 0 <= s <= 100


def test_empty_history_is_safe() -> None:
    score, tier = _compute_bankability_score([], [], [], [])[:2]
    assert 0 <= score <= 100
    assert tier in ("LOW", "MEDIUM", "HIGH")
