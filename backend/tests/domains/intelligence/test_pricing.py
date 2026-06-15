"""Model-keyed LLM pricing: defaults, env override, and unknown-model behaviour."""
from __future__ import annotations

import pytest

from src.domains.intelligence.llm import pricing


@pytest.fixture(autouse=True)
def _clear_pricing_cache() -> None:
    pricing._table.cache_clear()
    yield
    pricing._table.cache_clear()


def test_known_model_uses_default_rates() -> None:
    p = pricing.price_for("gemini-2.5-flash")
    assert (p.input_usd_per_mtok, p.output_usd_per_mtok) == (0.30, 2.50)


def test_unknown_model_costs_zero() -> None:
    # Degrade to zero rather than guessing a wrong rate for an unpriced model.
    assert pricing.cost_usd("totally-unknown-model", 1_000_000, 1_000_000) == 0.0


def test_cost_computation() -> None:
    assert pricing.cost_usd("gemini-2.5-flash", 1_000_000, 1_000_000) == pytest.approx(2.80)


def test_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "LLM_PRICING_JSON",
        '{"gemini-2.5-flash": {"input": 1.0, "output": 4.0}}',
    )
    pricing._table.cache_clear()
    assert pricing.cost_usd("gemini-2.5-flash", 1_000_000, 1_000_000) == pytest.approx(5.0)


def test_malformed_override_falls_back_to_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PRICING_JSON", "{not valid json")
    pricing._table.cache_clear()
    p = pricing.price_for("gemini-2.5-flash")
    assert p.input_usd_per_mtok == 0.30
