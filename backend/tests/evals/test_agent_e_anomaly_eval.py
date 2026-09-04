"""Agent E — deterministic anomaly-model eval (blocks CI; no LLM, no DB).

Agent E's HMM (Forward + Viterbi) and IsolationForest scoring are pure maths, so
their behaviour is pinned with fast, free asserts over **immutable labeled
fixtures** — a stable baseline against which the externalised Sprint-1 HMM priors
(``WatchdogTuning``) can be tuned and measured. If a tuning change regresses
state decoding or anomaly separation, these fail.

Labeling rationale (matches WatchdogTuning emission means):
  HEALTHY ≈ 0.55 · STABLE ≈ 0.85 · CRITICAL ≈ 1.20 (spending ratio vs budget).
"""
from __future__ import annotations

import numpy as np

from src.domains.intelligence.services.anomaly_service import (
    STATE_CRITICAL,
    STATE_HEALTHY,
    STATE_LABELS,
    STATE_STABLE,
    _forward_algorithm,
    _isolation_score,
    _viterbi,
)

# ── Immutable labeled fixtures ────────────────────────────────────────────────
HEALTHY_SERIES: tuple[float, ...] = (0.50, 0.55, 0.60, 0.52, 0.58, 0.54)
STABLE_SERIES: tuple[float, ...] = (0.85, 0.88, 0.82, 0.86, 0.84, 0.87)
CRISIS_SERIES: tuple[float, ...] = (0.55, 0.70, 0.95, 1.20, 1.35, 1.40)

# IsolationForest fixtures: (label, amounts). Fixed random_state → deterministic.
UNIFORM_AMOUNTS: tuple[float, ...] = (100.0, 101.0, 99.0, 100.5, 100.0, 99.5, 100.2)
OUTLIER_AMOUNTS: tuple[float, ...] = (100.0, 101.0, 99.0, 100.5, 100.0, 99.5, 50_000.0)


# ── HMM state decoding ────────────────────────────────────────────────────────

def test_forward_distribution_matches_label() -> None:
    assert int(np.argmax(_forward_algorithm(list(HEALTHY_SERIES)))) == STATE_HEALTHY
    assert int(np.argmax(_forward_algorithm(list(STABLE_SERIES)))) == STATE_STABLE
    assert int(np.argmax(_forward_algorithm(list(CRISIS_SERIES)))) == STATE_CRITICAL


def test_viterbi_endpoints_match_label() -> None:
    assert _viterbi(list(HEALTHY_SERIES))[-1] == STATE_HEALTHY
    assert _viterbi(list(STABLE_SERIES))[-1] == STATE_STABLE
    assert _viterbi(list(CRISIS_SERIES))[-1] == STATE_CRITICAL


def test_healthy_series_never_decodes_critical() -> None:
    # False-positive bound: a calm series must not spuriously visit CRITICAL.
    path = _viterbi(list(HEALTHY_SERIES))
    assert STATE_CRITICAL not in path
    assert all(0 <= s < len(STATE_LABELS) for s in path)


# ── IsolationForest anomaly separation ────────────────────────────────────────

def test_outlier_scores_higher_than_uniform() -> None:
    uniform = _isolation_score(list(UNIFORM_AMOUNTS))
    outlier = _isolation_score(list(OUTLIER_AMOUNTS))
    assert 0.0 <= uniform <= 1.0 and 0.0 <= outlier <= 1.0
    assert outlier > uniform                       # the injected anomaly is separated
    assert uniform < 0.6                           # false-positive bound on calm data


def test_below_min_samples_scores_zero() -> None:
    # Not enough history to fit → no anomaly claim (honest zero, not a guess).
    assert _isolation_score([100.0, 102.0]) == 0.0


def test_detection_rate_over_labeled_batch() -> None:
    # Each labeled pair: an outlier series must out-score its matched calm series.
    base = [100.0, 101.0, 99.0, 100.5, 100.0, 99.5]
    outliers = (25_000.0, 40_000.0, 80_000.0)
    detected = sum(
        1 for spike in outliers
        if _isolation_score([*base, spike]) > _isolation_score([*base, 100.0])
    )
    assert detected == len(outliers)   # 100% separation on the labeled batch
