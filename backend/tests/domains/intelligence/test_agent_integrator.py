"""Unit tests for Agent I (External Integrator) — explicit-provenance model.

Pins the honesty contract (gap A#1): every source carries a ``status`` of
live / manual / mock / unavailable, and KRA/Metropol are **never fabricated** —
they are ``unavailable`` unless real or manually supplied. FX uses a free
keyless provider (USD-based → KES cross-rates); M-Pesa hits the sandbox. The
HTTP caller is injected, so no network is touched.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from src.domains.intelligence.agents import i_integrator
from src.domains.intelligence.agents.i_integrator import (
    LIVE,
    MANUAL,
    MOCK,
    UNAVAILABLE,
    _fetch_fx,
    _fetch_kra_status,
    _fetch_metropol_score,
    _fetch_mpesa_data,
    _fetch_mpesa_ledger,
    _normalise_to_kes,
)


class _FakeCaller:
    def __init__(self, response: dict[str, Any]) -> None:
        self._response = response

    async def ainvoke(self, _payload: dict[str, Any]) -> dict[str, Any]:
        return self._response


# ── FX: free keyless provider, USD-based cross-rates ──────────────────────────

@pytest.mark.asyncio
async def test_fx_live_derives_kes_cross_rates() -> None:
    caller = _FakeCaller(
        {"status_code": 200, "data": {"rates": {"KES": 130.0, "EUR": 0.9, "GBP": 0.8}}}
    )
    fx = await _fetch_fx(caller)
    assert fx["status"] == LIVE
    assert fx["USD_KES"] == 130.0
    assert fx["EUR_KES"] == pytest.approx(130.0 / 0.9, abs=0.01)  # KES per EUR
    assert fx["GBP_KES"] == pytest.approx(162.5, abs=0.01)


@pytest.mark.asyncio
async def test_fx_unreachable_is_mock_in_dev_unavailable_in_prod(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    caller = _FakeCaller({"status_code": 503, "data": None})
    monkeypatch.setattr(i_integrator.settings, "ENVIRONMENT", "development")
    assert (await _fetch_fx(caller))["status"] == MOCK
    monkeypatch.setattr(i_integrator.settings, "ENVIRONMENT", "production")
    assert (await _fetch_fx(caller))["status"] == UNAVAILABLE


# ── M-Pesa: sandbox token + balance ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_mpesa_no_creds_degrades_by_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(i_integrator.settings, "MPESA_CONSUMER_KEY", "")
    monkeypatch.setattr(i_integrator.settings, "MPESA_CONSUMER_SECRET", "")
    caller = _FakeCaller({"status_code": 200, "data": {}})
    monkeypatch.setattr(i_integrator.settings, "ENVIRONMENT", "development")
    assert (await _fetch_mpesa_data(caller))["status"] == MOCK
    monkeypatch.setattr(i_integrator.settings, "ENVIRONMENT", "production")
    assert (await _fetch_mpesa_data(caller))["status"] == UNAVAILABLE


@pytest.mark.asyncio
async def test_mpesa_live_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(i_integrator.settings, "MPESA_CONSUMER_KEY", "k")
    monkeypatch.setattr(i_integrator.settings, "MPESA_CONSUMER_SECRET", "s")

    class _SeqCaller:
        async def ainvoke(self, payload: dict[str, Any]) -> dict[str, Any]:
            if "oauth" in payload["url"]:
                return {"status_code": 200, "data": {"access_token": "tok"}}
            return {"status_code": 200, "data": {"balance": 1}}

    out = await _fetch_mpesa_data(_SeqCaller())
    assert out["status"] == LIVE


# ── M-Pesa: real callback ledger feed (S6-3) ──────────────────────────────────

class _FakeResult:
    def __init__(self, rows: list) -> None:
        self._rows = rows

    def fetchall(self) -> list:
        return self._rows


class _FakeSession:
    def __init__(self, rows: list) -> None:
        self._rows = rows

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *_a: Any) -> bool:
        return False

    async def execute(self, *_a: Any, **_k: Any) -> _FakeResult:
        return _FakeResult(self._rows)


def _patch_ledger(monkeypatch: pytest.MonkeyPatch, rows: list) -> None:
    monkeypatch.setattr(i_integrator, "AsyncSessionLocal", lambda: _FakeSession(rows))


@pytest.mark.asyncio
async def test_mpesa_ledger_returns_live_feed(monkeypatch: pytest.MonkeyPatch) -> None:
    ts = datetime(2026, 6, 1, 9, 30, tzinfo=UTC)
    _patch_ledger(monkeypatch, [
        ("ABC123", 4500.00, "254700000001", "INV-1", ts),
        ("DEF456", 1200.50, "254700000002", None, ts),
    ])
    out = await _fetch_mpesa_ledger()
    assert out is not None
    assert out["status"] == LIVE
    assert out["feed"] == "callback"
    assert out["transaction_count"] == 2
    assert out["recent_credit_kes"] == 5700.50
    assert out["recent_transactions"][0]["trans_id"] == "ABC123"
    assert out["recent_transactions"][0]["timestamp"] == ts.isoformat()


@pytest.mark.asyncio
async def test_mpesa_ledger_empty_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_ledger(monkeypatch, [])
    assert await _fetch_mpesa_ledger() is None


@pytest.mark.asyncio
async def test_mpesa_ledger_db_error_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom() -> None:
        raise RuntimeError("no db")

    monkeypatch.setattr(i_integrator, "AsyncSessionLocal", _boom)
    assert await _fetch_mpesa_ledger() is None


@pytest.mark.asyncio
async def test_mpesa_data_prefers_ledger_over_sandbox_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Even with sandbox creds present, the real callback ledger wins.
    monkeypatch.setattr(i_integrator.settings, "MPESA_CONSUMER_KEY", "k")
    monkeypatch.setattr(i_integrator.settings, "MPESA_CONSUMER_SECRET", "s")
    ts = datetime(2026, 6, 1, tzinfo=UTC)
    _patch_ledger(monkeypatch, [("XYZ", 999.0, "254700000003", "INV-9", ts)])

    class _ShouldNotCall:
        async def ainvoke(self, _p: dict[str, Any]) -> dict[str, Any]:
            raise AssertionError("sandbox probe must not run when ledger has rows")

    out = await _fetch_mpesa_data(_ShouldNotCall())
    assert out["status"] == LIVE
    assert out["feed"] == "callback"
    assert out["transaction_count"] == 1


# ── Metropol & KRA: deferred — unavailable unless real or manual (never faked) ─

@pytest.mark.asyncio
async def test_metropol_unconfigured_is_unavailable_not_faked() -> None:
    out = await _fetch_metropol_score(_FakeCaller({}), customer_id="c1")
    assert out["status"] == UNAVAILABLE
    assert "score" not in out  # no fabricated credit score


@pytest.mark.asyncio
async def test_metropol_manual_entry() -> None:
    out = await _fetch_metropol_score(
        _FakeCaller({}), customer_id="c1", manual={"score": 710, "grade": "A"}
    )
    assert out["status"] == MANUAL
    assert out["score"] == 710


@pytest.mark.asyncio
async def test_kra_unconfigured_is_unavailable_not_faked() -> None:
    out = await _fetch_kra_status(_FakeCaller({}), pin_number="")
    assert out["status"] == UNAVAILABLE
    assert "compliance_status" not in out  # no fabricated VAT status


@pytest.mark.asyncio
async def test_kra_manual_entry() -> None:
    out = await _fetch_kra_status(
        _FakeCaller({}), pin_number="P051", manual={"compliance_status": "COMPLIANT"}
    )
    assert out["status"] == MANUAL
    assert out["compliance_status"] == "COMPLIANT"


# ── FX normaliser ─────────────────────────────────────────────────────────────

def test_normalise_kes_passthrough() -> None:
    assert _normalise_to_kes(1000.0, "KES", {"USD_KES": 130.0}) == 1000.0


def test_normalise_converts_with_rate() -> None:
    assert _normalise_to_kes(10.0, "USD", {"USD_KES": 130.0}) == 1300.0


def test_normalise_no_rate_passthrough() -> None:
    # FX unavailable → no rate key → return unchanged rather than guess.
    assert _normalise_to_kes(10.0, "USD", {"status": "unavailable"}) == 10.0
