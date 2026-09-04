"""Model-keyed LLM pricing: defaults, env override, and unknown-model behaviour.

Fireworks (dedicated deployment) and Featherless are GPU-hour / subscription
billed, so the built-in per-token defaults are zero; an operator supplies an
effective per-token rate via ``LLM_PRICING_JSON`` when they want the cost counter
populated. These tests cover that contract.
"""
from __future__ import annotations

import pytest

from src.domains.intelligence.llm import pricing

_BACKUP_MODEL = "google/gemma-4-31B-it"  # present in the built-in defaults (zero-rate)
_DEPLOYMENT = "accounts/acme/deployments/xyz"  # a Fireworks deployment id


@pytest.fixture(autouse=True)
def _clear_pricing_cache() -> None:
    pricing._table.cache_clear()
    yield
    pricing._table.cache_clear()


def test_default_model_is_zero_rate() -> None:
    # Built-in models default to zero (GPU-hour/subscription billed, not per-token).
    p = pricing.price_for(_BACKUP_MODEL)
    assert (p.input_usd_per_mtok, p.output_usd_per_mtok) == (0.0, 0.0)


def test_unknown_model_costs_zero() -> None:
    # Degrade to zero rather than guessing a wrong rate for an unpriced model.
    assert pricing.cost_usd("totally-unknown-model", 1_000_000, 1_000_000) == 0.0


def test_cost_computation_from_override(monkeypatch: pytest.MonkeyPatch) -> None:
    # Operator sets an effective per-token rate; verify the token × rate arithmetic.
    monkeypatch.setenv(
        "LLM_PRICING_JSON", f'{{"{_DEPLOYMENT}": {{"input": 0.30, "output": 2.50}}}}'
    )
    pricing._table.cache_clear()
    assert pricing.cost_usd(_DEPLOYMENT, 1_000_000, 1_000_000) == pytest.approx(2.80)


def test_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "LLM_PRICING_JSON", f'{{"{_DEPLOYMENT}": {{"input": 1.0, "output": 4.0}}}}'
    )
    pricing._table.cache_clear()
    assert pricing.cost_usd(_DEPLOYMENT, 1_000_000, 1_000_000) == pytest.approx(5.0)


def test_malformed_override_falls_back_to_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PRICING_JSON", "{not valid json")
    pricing._table.cache_clear()
    p = pricing.price_for(_BACKUP_MODEL)
    assert (p.input_usd_per_mtok, p.output_usd_per_mtok) == (0.0, 0.0)


# ── warn_if_unpriced (remediation C3) ─────────────────────────────────────────

def test_warn_if_unpriced_silent_in_development(caplog: pytest.LogCaptureFixture) -> None:
    pricing.warn_if_unpriced(_BACKUP_MODEL, environment="development")
    assert "cost telemetry is a no-op" not in caplog.text


def test_warn_if_unpriced_warns_for_zero_rate_model_outside_dev(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level("WARNING"):
        pricing.warn_if_unpriced(_BACKUP_MODEL, environment="production")
    assert "cost telemetry is a no-op" in caplog.text
    assert _BACKUP_MODEL in caplog.text


def test_warn_if_unpriced_silent_when_model_is_priced(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(
        "LLM_PRICING_JSON", f'{{"{_DEPLOYMENT}": {{"input": 0.30, "output": 2.50}}}}'
    )
    pricing._table.cache_clear()
    with caplog.at_level("WARNING"):
        pricing.warn_if_unpriced(_DEPLOYMENT, environment="staging")
    assert "cost telemetry is a no-op" not in caplog.text
