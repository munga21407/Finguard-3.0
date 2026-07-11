"""Externally-configurable tuning constants for the intelligence agents.

Domain constants that a business analyst (not an engineer) might legitimately
change — tax rates, HMM priors, credit-scoring weights, reconciliation
thresholds — used to be hard-coded inside each agent module.  That meant every
tweak required a code change + deploy, and the values were invisible to
operators.

This module centralises them as typed, frozen dataclasses with **defaults that
exactly reproduce the previous hard-coded behaviour**.  Each group can be
overridden **wholesale** via the ``AGENT_TUNING_JSON`` env var — a JSON object
keyed by section (``reconciler`` / ``watchdog`` / ``auditor`` / ``bankability``)
— mirroring the ``LLM_PRICING_JSON`` pattern in ``llm/pricing.py``.  A malformed
or partial section falls back to that section's defaults (failure is isolated
per section, never silent for the whole app — it's logged).

``validate_agent_tuning()`` enforces sanity (probabilities sum to 1, rates in
range, tiers ordered).  It hard-fails in production and warns in development,
mirroring ``core.config.Settings._validate_production``.

NOTE (follow-up, Sprint 1): a DB-backed ``agent_config`` table for *runtime*
changes without a restart — and effective-dated tax-rate history so historical
audits use period-correct rates — is deliberately out of scope here.  The
``get_*_tuning()`` accessors are the seam where that layer will slot in.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field, fields
from functools import lru_cache
from typing import Any

logger = logging.getLogger(__name__)

_ENV_VAR = "AGENT_TUNING_JSON"


# ---------------------------------------------------------------------------
# Agent C — Reconciliation Detective
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ReconcilerTuning:
    """Two-pass reconciliation batch sizes and match thresholds."""

    txn_batch: int = 100          # M-Pesa / bank lines per reconciliation run
    inv_limit: int = 500          # max open invoices loaded per run
    fuzzy_threshold: float = 65.0  # rapidfuzz token_sort_ratio min for Pass 2 candidacy
    semantic_threshold: float = 0.60   # the model match_score min to confirm a match
    fuzzy_match_boundary: float = 0.90  # >= this scores as "fuzzy", below as "semantic"
    amount_tolerance_kes: float = 1.0   # Pass 1 exact-amount tolerance
    date_window_days: int = 2           # Pass 1 date-proximity window
    pass2_candidate_cap: int = 50       # max fuzzy candidates sent to the model per run


# ---------------------------------------------------------------------------
# Agent E — Budget Watchdog (HMM priors + detectors)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class WatchdogTuning:
    """Hidden-Markov-Model priors and anomaly/duplicate detector thresholds.

    States are ordered [HEALTHY, STABLE, CRITICAL].  ``emission_params`` is one
    (mean, std) Gaussian per state over the normalised spending ratio;
    ``transition`` is the row-stochastic A[from][to] matrix; ``initial_pi`` is
    the initial state distribution.
    """

    emission_params: tuple[tuple[float, float], ...] = (
        (0.55, 0.15),   # HEALTHY:  typically <=70% of budget
        (0.85, 0.12),   # STABLE:   around 85-90% of budget
        (1.20, 0.22),   # CRITICAL: over budget by 20%+
    )
    transition: tuple[tuple[float, ...], ...] = (
        (0.85, 0.13, 0.02),
        (0.10, 0.78, 0.12),
        (0.05, 0.20, 0.75),
    )
    initial_pi: tuple[float, ...] = (0.80, 0.15, 0.05)
    duplicate_threshold: float = 88.0   # rapidfuzz token_sort_ratio (0-100)
    isolation_min_samples: int = 5      # min samples before IsolationForest scores


# ---------------------------------------------------------------------------
# Agent F — Tax Auditor (Kenya tax constants)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AuditorTuning:
    """Kenya tax rates/thresholds used by the deterministic tax engine.

    Effective-dated history (so a 2023 audit uses 2023 rates) is a documented
    Sprint-1 follow-up; these are the current-period values.
    """

    vat_rate: float = 0.16
    vat_threshold_annual_kes: float = 5_000_000.0   # KRA mandatory VAT registration
    cit_rate: float = 0.30                           # corporate income tax
    tot_rate: float = 0.03                           # turnover tax (KES 1M-50M band)
    aml_reporting_threshold_kes: float = 1_000_000.0  # single-tx AML flag


# ---------------------------------------------------------------------------
# Agent G — Credit Strategist (bankability scoring)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ClassifierTuning:
    """Agent B batch sizing + backlog drain (Sprint 5)."""

    batch_size: int = 50          # ledger entries classified per batch
    drain_max_batches: int = 1    # max batches the persistence sweep drains per run


@dataclass(frozen=True)
class ReceiptTuning:
    """Agent A / Receipt-scanner OCR taxonomy + multi-pass retry (Sprint 6).

    ``categories`` is the closed expense-taxonomy the vision model must choose
    from; operators may extend it via config without a deploy (S6-6) as long as
    ``"other"`` remains the catch-all fallback. Low-confidence scans below
    ``ocr_min_confidence`` are re-run once with a higher-fidelity vision model
    when ``hifi_retry_enabled`` is set.
    """

    categories: tuple[str, ...] = ("supplies", "services", "utilities", "travel", "other")
    ocr_min_confidence: float = 0.6
    hifi_retry_enabled: bool = True


@dataclass(frozen=True)
class BankabilityTuning:
    """Weights, expense-ratio bands, and risk-tier cutoffs for the 0-100 score.

    ``ratio_bands`` is an ordered list of (exclusive_upper_bound, points): the
    first band whose bound the opex/revenue ratio is *below* awards its points;
    a ratio at/above the last bound scores 0.
    """

    trend_max: int = 30
    ratio_max: int = 30
    consistency_max: int = 20
    solvency_max: int = 20
    ratio_bands: tuple[tuple[float, int], ...] = (
        (0.50, 30),
        (0.65, 24),
        (0.80, 16),
        (0.95, 8),
        (1.00, 3),
    )
    tier_low_min: int = 75      # score >= this -> LOW risk
    tier_medium_min: int = 45   # score >= this -> MEDIUM, else HIGH


# ---------------------------------------------------------------------------
# Aggregate + JSON override loading
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AgentTuning:
    reconciler: ReconcilerTuning = field(default_factory=ReconcilerTuning)
    watchdog: WatchdogTuning = field(default_factory=WatchdogTuning)
    auditor: AuditorTuning = field(default_factory=AuditorTuning)
    bankability: BankabilityTuning = field(default_factory=BankabilityTuning)
    classifier: ClassifierTuning = field(default_factory=ClassifierTuning)
    receipt: ReceiptTuning = field(default_factory=ReceiptTuning)


_SECTIONS: dict[str, type] = {
    "reconciler": ReconcilerTuning,
    "watchdog": WatchdogTuning,
    "auditor": AuditorTuning,
    "bankability": BankabilityTuning,
    "classifier": ClassifierTuning,
    "receipt": ReceiptTuning,
}


def _coerce_section(cls: type, raw: dict[str, Any]) -> Any:
    """Build a frozen tuning dataclass from a JSON dict.

    Tuple-typed fields (matrices, bands) arrive as JSON arrays and are converted
    back to nested tuples so the dataclass stays hashable/immutable.  Unknown
    keys are rejected (KeyError-like) so a typo doesn't silently no-op.
    """
    known = {f.name for f in fields(cls)}
    unknown = set(raw) - known
    if unknown:
        raise ValueError(f"{cls.__name__}: unknown keys {sorted(unknown)}")

    kwargs: dict[str, Any] = {}
    for f in fields(cls):
        if f.name not in raw:
            continue
        value = raw[f.name]
        if isinstance(value, list):
            value = _to_tuple(value)
        kwargs[f.name] = value
    return cls(**kwargs)


def _to_tuple(value: Any) -> Any:
    """Recursively convert nested lists to nested tuples."""
    if isinstance(value, list):
        return tuple(_to_tuple(v) for v in value)
    return value


# Process-global runtime overlay (populated from the DB ``agent_config`` table
# by ``db_tuning.refresh_agent_tuning_from_db``).  Section-level precedence is
# env > this overlay > code default.  Mutating it clears the cache so the next
# accessor call rebuilds the merged view.
_db_overlay: dict[str, Any] = {}


def _env_sections() -> dict[str, Any]:
    """Parse AGENT_TUNING_JSON into ``{section: dataclass}`` for present sections.

    A malformed whole document yields ``{}`` (all sections defer to overlay /
    default); a malformed *single* section is skipped (that one section defers).
    """
    raw = os.environ.get(_ENV_VAR, "").strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("AGENT_TUNING_JSON must be a JSON object")
    except ValueError:
        logger.exception(
            "Invalid %s — ignoring env overrides for agent tuning", _ENV_VAR
        )
        return {}

    out: dict[str, Any] = {}
    for name, cls in _SECTIONS.items():
        if name not in data:
            continue
        try:
            out[name] = _coerce_section(cls, data[name])
        except (ValueError, TypeError):
            logger.exception(
                "Invalid %s section %r — deferring that section to overlay/default",
                _ENV_VAR,
                name,
            )
    return out


def set_db_overlay(sections: dict[str, Any]) -> None:
    """Replace the runtime DB overlay (dict of section-name -> tuning dataclass)."""
    global _db_overlay
    _db_overlay = dict(sections)
    get_agent_tuning.cache_clear()


def clear_db_overlay() -> None:
    """Drop the runtime DB overlay (back to env > default)."""
    set_db_overlay({})


@lru_cache(maxsize=1)
def get_agent_tuning() -> AgentTuning:
    """Return the cached merged AgentTuning.

    Section-level precedence: env (AGENT_TUNING_JSON) > DB overlay > code default.
    Cached until ``set_db_overlay`` invalidates it (env is static per process).
    """
    env = _env_sections()
    sections: dict[str, Any] = {}
    for name, cls in _SECTIONS.items():
        if name in env:
            sections[name] = env[name]
        elif name in _db_overlay:
            sections[name] = _db_overlay[name]
        else:
            sections[name] = cls()
    return AgentTuning(**sections)


def valid_sections() -> tuple[str, ...]:
    """The tuning section names an operator may override (agent_config keys)."""
    return tuple(_SECTIONS)


def coerce_section(section: str, raw: dict[str, Any]) -> Any:
    """Public helper: build a tuning dataclass for ``section`` from a JSON dict.

    Used by the DB layer to turn an ``agent_config`` row payload into a validated
    dataclass.  Raises ValueError for an unknown section or bad keys.
    """
    cls = _SECTIONS.get(section)
    if cls is None:
        raise ValueError(f"unknown tuning section {section!r}")
    return _coerce_section(cls, raw)


# Convenience per-section accessors (the seam a future DB layer plugs into).
def get_reconciler_tuning() -> ReconcilerTuning:
    return get_agent_tuning().reconciler


def get_watchdog_tuning() -> WatchdogTuning:
    return get_agent_tuning().watchdog


def get_auditor_tuning() -> AuditorTuning:
    return get_agent_tuning().auditor


def get_bankability_tuning() -> BankabilityTuning:
    return get_agent_tuning().bankability


def get_classifier_tuning() -> ClassifierTuning:
    return get_agent_tuning().classifier


def get_receipt_tuning() -> ReceiptTuning:
    return get_agent_tuning().receipt


# ---------------------------------------------------------------------------
# Validation — fail-in-prod, warn-in-dev
# ---------------------------------------------------------------------------

_PROB_TOL = 1e-6


def _check(problems: list[str], cond: bool, msg: str) -> None:
    if not cond:
        problems.append(msg)


def validate_agent_tuning(tuning: AgentTuning | None = None) -> list[str]:
    """Return a list of tuning problems; empty when all values are sane.

    Called at import time (see bottom of module): in production a non-empty list
    raises ValueError so the app refuses to boot on nonsensical tuning; outside
    production it is logged as a warning so local dev / CI stay frictionless.
    """
    t = tuning or get_agent_tuning()
    problems: list[str] = []

    # ── Reconciler ──────────────────────────────────────────────────────────
    r = t.reconciler
    _check(problems, r.txn_batch > 0, "reconciler.txn_batch must be > 0")
    _check(problems, r.inv_limit > 0, "reconciler.inv_limit must be > 0")
    _check(problems, 0 <= r.fuzzy_threshold <= 100, "reconciler.fuzzy_threshold must be 0-100")
    _check(
        problems,
        0.0 <= r.semantic_threshold <= 1.0,
        "reconciler.semantic_threshold must be 0.0-1.0",
    )
    _check(
        problems,
        0.0 <= r.fuzzy_match_boundary <= 1.0,
        "reconciler.fuzzy_match_boundary must be 0.0-1.0",
    )
    _check(problems, r.amount_tolerance_kes >= 0, "reconciler.amount_tolerance_kes must be >= 0")
    _check(problems, r.date_window_days >= 0, "reconciler.date_window_days must be >= 0")
    _check(problems, r.pass2_candidate_cap > 0, "reconciler.pass2_candidate_cap must be > 0")

    # ── Watchdog (HMM) ──────────────────────────────────────────────────────
    w = t.watchdog
    n_states = len(w.emission_params)
    _check(problems, n_states == 3, "watchdog.emission_params must have 3 states")
    _check(
        problems,
        all(sd > 0 for _, sd in w.emission_params),
        "watchdog.emission_params std-dev must be > 0 for every state",
    )
    _check(
        problems,
        abs(sum(w.initial_pi) - 1.0) < _PROB_TOL and len(w.initial_pi) == n_states,
        "watchdog.initial_pi must sum to 1.0 with one entry per state",
    )
    _check(
        problems,
        len(w.transition) == n_states
        and all(len(row) == n_states for row in w.transition),
        "watchdog.transition must be a square matrix matching the state count",
    )
    _check(
        problems,
        all(abs(sum(row) - 1.0) < _PROB_TOL for row in w.transition),
        "watchdog.transition rows must each sum to 1.0 (row-stochastic)",
    )
    _check(
        problems,
        0 <= w.duplicate_threshold <= 100,
        "watchdog.duplicate_threshold must be 0-100",
    )
    _check(problems, w.isolation_min_samples >= 1, "watchdog.isolation_min_samples must be >= 1")

    # ── Auditor (tax) ───────────────────────────────────────────────────────
    a = t.auditor
    _check(problems, 0.0 <= a.vat_rate <= 1.0, "auditor.vat_rate must be 0.0-1.0")
    _check(problems, 0.0 <= a.cit_rate <= 1.0, "auditor.cit_rate must be 0.0-1.0")
    _check(problems, 0.0 <= a.tot_rate <= 1.0, "auditor.tot_rate must be 0.0-1.0")
    _check(
        problems,
        a.vat_threshold_annual_kes >= 0,
        "auditor.vat_threshold_annual_kes must be >= 0",
    )
    _check(
        problems,
        a.aml_reporting_threshold_kes >= 0,
        "auditor.aml_reporting_threshold_kes must be >= 0",
    )

    # ── Bankability ─────────────────────────────────────────────────────────
    b = t.bankability
    _check(
        problems,
        b.tier_low_min > b.tier_medium_min,
        "bankability.tier_low_min must be greater than tier_medium_min",
    )
    _check(
        problems,
        all(x >= 0 for x in (b.trend_max, b.ratio_max, b.consistency_max, b.solvency_max)),
        "bankability sub-score max weights must be >= 0",
    )
    _check(
        problems,
        bool(b.ratio_bands)
        and all(
            u1 < u2
            for (u1, _), (u2, _) in zip(b.ratio_bands, b.ratio_bands[1:], strict=False)
        ),
        "bankability.ratio_bands upper bounds must be strictly ascending",
    )

    # ── Classifier ──────────────────────────────────────────────────────────
    c = t.classifier
    _check(problems, c.batch_size > 0, "classifier.batch_size must be > 0")
    _check(problems, c.drain_max_batches >= 1, "classifier.drain_max_batches must be >= 1")

    # ── Receipt (OCR taxonomy + multi-pass) ─────────────────────────────────
    rc = t.receipt
    _check(problems, len(rc.categories) >= 1, "receipt.categories must be non-empty")
    _check(
        problems,
        "other" in rc.categories,
        "receipt.categories must include 'other' as the catch-all fallback",
    )
    _check(
        problems,
        all(isinstance(x, str) and x == x.lower() and x for x in rc.categories),
        "receipt.categories must be non-empty lowercase strings",
    )
    _check(
        problems,
        0.0 <= rc.ocr_min_confidence <= 1.0,
        "receipt.ocr_min_confidence must be 0.0-1.0",
    )

    return problems


def _enforce_on_import() -> None:
    problems = validate_agent_tuning()
    if not problems:
        return
    # Local import to avoid a config import cycle at module load.
    from src.core.config import settings  # noqa: PLC0415

    message = "Invalid agent tuning: " + "; ".join(problems)
    if settings.ENVIRONMENT == "production":
        raise ValueError(message)
    logger.warning(message)


_enforce_on_import()
