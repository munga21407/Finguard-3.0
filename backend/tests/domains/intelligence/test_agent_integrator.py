"""Unit tests for Agent I (External Integrator) — explicit-provenance model.

Pins the honesty contract (gap A#1): every source carries a ``status`` of
live / manual / mock / unavailable, and KRA/Metropol are **never fabricated** —
they are ``unavailable`` unless real or manually supplied. FX uses a free
keyless provider (USD-based → KES cross-rates); M-Pesa hits the sandbox. The
HTTP caller is injected, so no network is touched.
"""
from __future__ import annotations

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
