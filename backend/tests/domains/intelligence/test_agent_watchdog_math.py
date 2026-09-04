"""Deterministic unit tests for Agent E (Budget Watchdog) statistical core.

The HMM (forward/Viterbi), the exponentially-weighted anomaly score, the
IsolationForest scorer, and the rapidfuzz duplicate detector are pure functions
over numeric inputs — no LLM, no DB — so they're pinned here as fast, free tests.
Emission means (HEALTHY≈0.55, STABLE≈0.85, CRITICAL≈1.20) anchor the
state-recovery assertions.
"""
from __future__ import annotations

import math

import pytest

from src.domains.intelligence.services.anomaly_service import (
    STATE_CRITICAL,
    STATE_HEALTHY,
    _detect_duplicate,
    _forward_algorithm,
    _gaussian_log_prob,
    _isolation_score,
    _viterbi,
    _weighted_anomaly_score,
)

# ── _gaussian_log_prob ────────────────────────────────────────────────────────

def test_gaussian_log_prob_matches_formula() -> None:
    x, mean, std = 0.6, 0.55, 0.15
    expected = -0.5 * ((x - mean) / std) ** 2 - math.log(std * math.sqrt(2 * math.pi))
    assert _gaussian_log_prob(x, mean, std) == pytest.approx(expected)


def test_gaussian_log_prob_peaks_at_mean() -> None:
    at_mean = _gaussian_log_prob(0.55, 0.55, 0.15)
    far = _gaussian_log_prob(1.5, 0.55, 0.15)
    assert at_mean > far


# ── forward algorithm (posterior over states) ────────────────────────────────

def test_forward_returns_normalised_distribution() -> None:
    probs = _forward_algorithm([0.5, 0.6, 0.55, 0.5])
    assert len(probs) == 3
    assert all(0.0 <= p <= 1.0 for p in probs)
    assert float(probs.sum()) == pytest.approx(1.0)


def test_forward_healthy_observations_favour_healthy_state() -> None:
    probs = _forward_algorithm([0.5, 0.55, 0.52, 0.48, 0.5])
    assert int(probs.argmax()) == STATE_HEALTHY


def test_forward_overbudget_observations_favour_critical_state() -> None:
    probs = _forward_algorithm([1.25, 1.3, 1.2, 1.35, 1.28])
    assert int(probs.argmax()) == STATE_CRITICAL


# ── Viterbi (most-likely path) ────────────────────────────────────────────────

def test_viterbi_path_length_and_domain() -> None:
    obs = [0.5, 0.9, 1.3, 0.55]
    path = _viterbi(obs)
    assert len(path) == len(obs)
    assert all(s in (0, 1, 2) for s in path)


def test_viterbi_sustained_overbudget_ends_critical() -> None:
    path = _viterbi([0.5, 0.8, 1.2, 1.3, 1.4])
    assert path[-1] == STATE_CRITICAL


# ── weighted anomaly score ────────────────────────────────────────────────────

def test_weighted_score_empty_is_zero() -> None:
    assert _weighted_anomaly_score([]) == 0.0


def test_weighted_score_all_healthy_is_zero() -> None:
    assert _weighted_anomaly_score([0, 0, 0, 0]) == 0.0


def test_weighted_score_all_critical_is_bounded_near_one() -> None:
    score = _weighted_anomaly_score([2, 2, 2, 2])
    assert 0.9 <= score <= 1.0


def test_weighted_score_recency_weighted() -> None:
    # Recent CRITICAL states should weigh more than early ones.
    recent_bad = _weighted_anomaly_score([0, 0, 2, 2])
    early_bad = _weighted_anomaly_score([2, 2, 0, 0])
    assert recent_bad > early_bad


# ── IsolationForest scorer ────────────────────────────────────────────────────

def test_isolation_below_min_samples_is_zero() -> None:
    assert _isolation_score([100.0, 102.0]) == 0.0


def test_isolation_outlier_scores_higher_than_uniform() -> None:
    uniform = _isolation_score([100.0, 101.0, 99.0, 100.5, 100.0, 99.5])
    with_outlier = _isolation_score([100.0, 101.0, 99.0, 100.5, 100.0, 50_000.0])
    assert 0.0 <= uniform <= 1.0
    assert 0.0 <= with_outlier <= 1.0
    assert with_outlier > uniform


# ── duplicate detection ───────────────────────────────────────────────────────

def test_detect_duplicate_identical_record() -> None:
    candidate = {"vendor": "Acme Ltd", "amount": "12500", "invoice_number": "INV-001"}
    is_dup, score = _detect_duplicate(candidate, [dict(candidate)])
    assert is_dup is True
    assert score == pytest.approx(1.0)


def test_detect_duplicate_distinct_record() -> None:
    candidate = {"vendor": "Acme Ltd", "amount": "12500", "invoice_number": "INV-001"}
    other = {"vendor": "Globex Inc", "amount": "999", "invoice_number": "ZZ-742"}
    is_dup, score = _detect_duplicate(candidate, [other])
    assert is_dup is False
    assert 0.0 <= score < 0.88


def test_detect_duplicate_empty_reference_list() -> None:
    is_dup, score = _detect_duplicate({"vendor": "X", "amount": "1", "invoice_number": "A"}, [])
    assert is_dup is False
    assert score == 0.0
