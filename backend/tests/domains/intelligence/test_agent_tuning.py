"""Sprint 1 — agent tuning config: defaults, overrides, and validation.

These are hermetic sync tests (no DB, no LLM).  The headline guarantee is the
*no behaviour change* one: every externalised default must equal the value that
was hard-coded in the agent before Sprint 1.
"""
from __future__ import annotations

import json

import pytest

from src.domains.intelligence.tuning import (
    AgentTuning,
    AuditorTuning,
    BankabilityTuning,
    ReconcilerTuning,
    WatchdogTuning,
    clear_db_overlay,
    get_agent_tuning,
    validate_agent_tuning,
)


@pytest.fixture(autouse=True)
def _clear_tuning_cache():
    """The tuning accessor is lru_cached; reset it + the overlay around each test."""
    clear_db_overlay()
    get_agent_tuning.cache_clear()
    yield
    clear_db_overlay()
    get_agent_tuning.cache_clear()


# ---------------------------------------------------------------------------
# Defaults reproduce the previously hard-coded constants (no behaviour change)
# ---------------------------------------------------------------------------

def test_reconciler_defaults_match_legacy_constants() -> None:
    r = ReconcilerTuning()
    assert r.txn_batch == 100
    assert r.inv_limit == 500
    assert r.fuzzy_threshold == 65.0
    assert r.semantic_threshold == 0.60
    assert r.fuzzy_match_boundary == 0.90
    assert r.amount_tolerance_kes == 1.0
    assert r.date_window_days == 2


def test_watchdog_defaults_match_legacy_constants() -> None:
    w = WatchdogTuning()
    assert w.emission_params == ((0.55, 0.15), (0.85, 0.12), (1.20, 0.22))
    assert w.transition == (
        (0.85, 0.13, 0.02),
        (0.10, 0.78, 0.12),
        (0.05, 0.20, 0.75),
    )
    assert w.initial_pi == (0.80, 0.15, 0.05)
    assert w.duplicate_threshold == 88.0
    assert w.isolation_min_samples == 5


def test_auditor_defaults_match_legacy_constants() -> None:
    a = AuditorTuning()
    assert a.vat_rate == 0.16
    assert a.vat_threshold_annual_kes == 5_000_000.0
    assert a.cit_rate == 0.30
    assert a.tot_rate == 0.03
    assert a.aml_reporting_threshold_kes == 1_000_000.0


def test_bankability_defaults_match_legacy_constants() -> None:
    b = BankabilityTuning()
    assert (b.trend_max, b.ratio_max, b.consistency_max, b.solvency_max) == (30, 30, 20, 20)
    assert b.ratio_bands == ((0.50, 30), (0.65, 24), (0.80, 16), (0.95, 8), (1.00, 3))
    assert b.tier_low_min == 75
    assert b.tier_medium_min == 45


def test_agent_module_constants_bind_to_defaults() -> None:
    """The agent modules derive their constants from the tuning defaults.

    (Agent F no longer keeps module-level tax constants — it resolves period-
    correct rates at invocation via db_tuning.get_effective_auditor_tuning.)
    """
    from src.domains.intelligence.agents import c_reconciler, e_watchdog

    assert c_reconciler._FUZZY_THRESHOLD == 65.0
    assert c_reconciler._SEMANTIC_THRESHOLD == 0.60
    assert e_watchdog.DUPLICATE_THRESHOLD == 88.0
    assert list(e_watchdog.INITIAL_PI) == [0.80, 0.15, 0.05]


def test_watchdog_apply_tuning_rebinds_from_overlay() -> None:
    """_apply_watchdog_tuning picks up a runtime overlay change (no restart)."""
    from src.domains.intelligence.agents import e_watchdog
    from src.domains.intelligence.tuning import clear_db_overlay, set_db_overlay

    try:
        set_db_overlay({"watchdog": WatchdogTuning(duplicate_threshold=95.0)})
        e_watchdog._apply_watchdog_tuning()
        assert e_watchdog.DUPLICATE_THRESHOLD == 95.0
    finally:
        clear_db_overlay()
        e_watchdog._apply_watchdog_tuning()  # restore module globals to defaults
    assert e_watchdog.DUPLICATE_THRESHOLD == 88.0


# ---------------------------------------------------------------------------
# Default tuning is valid
# ---------------------------------------------------------------------------

def test_defaults_pass_validation() -> None:
    assert validate_agent_tuning(AgentTuning()) == []


# ---------------------------------------------------------------------------
# JSON env override + per-section graceful fallback
# ---------------------------------------------------------------------------

def test_env_override_replaces_section(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "AGENT_TUNING_JSON",
        json.dumps({"auditor": {"vat_rate": 0.14, "cit_rate": 0.25}}),
    )
    get_agent_tuning.cache_clear()
    tuning = get_agent_tuning()
    assert tuning.auditor.vat_rate == 0.14
    assert tuning.auditor.cit_rate == 0.25
    # Untouched sections keep defaults.
    assert tuning.reconciler.txn_batch == 100


def test_env_override_matrix_roundtrips_to_tuples(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "AGENT_TUNING_JSON",
        json.dumps({"watchdog": {"initial_pi": [0.5, 0.3, 0.2]}}),
    )
    get_agent_tuning.cache_clear()
    tuning = get_agent_tuning()
    assert tuning.watchdog.initial_pi == (0.5, 0.3, 0.2)


def test_malformed_json_falls_back_to_all_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_TUNING_JSON", "{not valid json")
    get_agent_tuning.cache_clear()
    assert get_agent_tuning() == AgentTuning()


def test_bad_section_falls_back_only_that_section(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "AGENT_TUNING_JSON",
        json.dumps(
            {
                "auditor": {"nonexistent_field": 1},   # invalid -> auditor defaults
                "reconciler": {"txn_batch": 42},        # valid -> applied
            }
        ),
    )
    get_agent_tuning.cache_clear()
    tuning = get_agent_tuning()
    assert tuning.auditor == AuditorTuning()       # fell back
    assert tuning.reconciler.txn_batch == 42       # applied


# ---------------------------------------------------------------------------
# Validation rejects nonsensical overrides
# ---------------------------------------------------------------------------

def test_validation_flags_non_stochastic_transition() -> None:
    bad = AgentTuning(
        watchdog=WatchdogTuning(transition=((0.5, 0.5, 0.5), (0.1, 0.8, 0.1), (0.0, 0.0, 1.0)))
    )
    problems = validate_agent_tuning(bad)
    assert any("row-stochastic" in p for p in problems)


def test_validation_flags_initial_pi_not_summing_to_one() -> None:
    bad = AgentTuning(watchdog=WatchdogTuning(initial_pi=(0.5, 0.2, 0.1)))
    assert any("initial_pi" in p for p in validate_agent_tuning(bad))


def test_validation_flags_inverted_tiers() -> None:
    bad = AgentTuning(bankability=BankabilityTuning(tier_low_min=40, tier_medium_min=60))
    assert any("tier_low_min" in p for p in validate_agent_tuning(bad))


def test_validation_flags_out_of_range_tax_rate() -> None:
    bad = AgentTuning(auditor=AuditorTuning(vat_rate=1.6))
    assert any("vat_rate" in p for p in validate_agent_tuning(bad))


def test_validation_flags_non_ascending_ratio_bands() -> None:
    bad = AgentTuning(
        bankability=BankabilityTuning(ratio_bands=((0.80, 30), (0.50, 24)))
    )
    assert any("ratio_bands" in p for p in validate_agent_tuning(bad))
