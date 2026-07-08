"""DB-backed tuning layer: overlay precedence + effective-dated tax.

The overlay-precedence tests are hermetic (no DB). The effective-dated tax test
uses a fake async session so the *selection* logic (latest-per-key, fall back to
base) is unit-tested; the SQL ``effective_from <= as_of`` filter itself is DB
behaviour, exercised only under integration.
"""
from __future__ import annotations

import datetime as dt
import json
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest

from src.domains.intelligence.db_tuning import (
    _validate_section,
    get_effective_auditor_tuning,
)
from src.domains.intelligence.tuning import (
    AuditorTuning,
    ReconcilerTuning,
    clear_db_overlay,
    get_agent_tuning,
    get_auditor_tuning,
    get_reconciler_tuning,
    set_db_overlay,
)


@pytest.fixture(autouse=True)
def _reset():
    clear_db_overlay()
    get_agent_tuning.cache_clear()
    yield
    clear_db_overlay()
    get_agent_tuning.cache_clear()


# ---------------------------------------------------------------------------
# Overlay precedence: env > DB overlay > default
# ---------------------------------------------------------------------------

def test_db_overlay_applies_over_default() -> None:
    set_db_overlay({"reconciler": ReconcilerTuning(txn_batch=7)})
    assert get_reconciler_tuning().txn_batch == 7


def test_db_overlay_only_affects_its_section() -> None:
    set_db_overlay({"auditor": AuditorTuning(vat_rate=0.10)})
    assert get_auditor_tuning().vat_rate == 0.10
    assert get_reconciler_tuning().txn_batch == 100  # untouched -> default


def test_env_beats_db_overlay(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_TUNING_JSON", json.dumps({"reconciler": {"txn_batch": 9}}))
    set_db_overlay({"reconciler": ReconcilerTuning(txn_batch=7)})  # also clears cache
    assert get_reconciler_tuning().txn_batch == 9  # env pin wins


def test_clear_overlay_reverts_to_default() -> None:
    set_db_overlay({"reconciler": ReconcilerTuning(txn_batch=7)})
    clear_db_overlay()
    assert get_reconciler_tuning().txn_batch == 100


# ---------------------------------------------------------------------------
# Section validation helper (used to drop bad runtime rows)
# ---------------------------------------------------------------------------

def test_validate_section_passes_for_good_instance() -> None:
    assert _validate_section("auditor", AuditorTuning(vat_rate=0.14)) == []


def test_validate_section_flags_bad_instance() -> None:
    problems = _validate_section("auditor", AuditorTuning(vat_rate=1.6))
    assert problems and all(p.startswith("auditor.") for p in problems)


# ---------------------------------------------------------------------------
# Effective-dated tax selection
# ---------------------------------------------------------------------------

class _FakeResult:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def scalars(self) -> _FakeResult:
        return self

    def all(self) -> list[Any]:
        return self._rows


class _FakeSession:
    """Minimal stand-in: returns the given rows regardless of the statement."""

    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    async def execute(self, _stmt: Any) -> _FakeResult:
        return _FakeResult(self._rows)


def _rate(key: str, y: int, m: int, d: int, value: str) -> SimpleNamespace:
    return SimpleNamespace(rate_key=key, effective_from=dt.date(y, m, d), rate=Decimal(value))


@pytest.mark.asyncio
async def test_effective_tax_picks_latest_per_key_and_falls_back() -> None:
    rows = [
        _rate("vat_rate", 2022, 1, 1, "0.14"),
        _rate("vat_rate", 2023, 7, 1, "0.16"),   # latest for vat_rate
        _rate("aml_reporting_threshold_kes", 2020, 1, 1, "500000"),
    ]
    eff = await get_effective_auditor_tuning(_FakeSession(rows), dt.date(2024, 1, 1))  # type: ignore[arg-type]
    assert eff.vat_rate == 0.16                       # latest schedule row wins
    assert eff.aml_reporting_threshold_kes == 500000.0
    assert eff.cit_rate == AuditorTuning().cit_rate   # no row -> base default


@pytest.mark.asyncio
async def test_effective_tax_no_rows_returns_base() -> None:
    eff = await get_effective_auditor_tuning(_FakeSession([]), dt.date(2024, 1, 1))  # type: ignore[arg-type]
    assert eff == get_auditor_tuning()
