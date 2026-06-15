"""Unit tests for Agent I (External Integrator) fallback + normalisation.

Pins the documented-but-risky behaviour (gap A#1): when an API key is absent or
a call fails, each fetch silently returns mock data flagged with
``data_source == "mock_sandbox"``.  These tests assert the flag is present so a
caller/dashboard can detect degraded data, and cover the live-success path and
the FX normaliser.  The HTTP caller is injected, so no network is touched.
"""
from __future__ import annotations

from typing import Any

import pytest

from src.domains.intelligence.agents import i_integrator
from src.domains.intelligence.agents.i_integrator import (
    _fetch_cbk_fx,
    _fetch_mpesa_data,
    _mock_credit_score,
    _mock_fx_rates,
    _mock_kra_status,
    _mock_mpesa,
    _normalise_to_kes,
)


class _FakeCaller:
    """Stand-in for the http_caller tool with a scripted ainvoke response."""

    def __init__(self, response: dict[str, Any]) -> None:
        self._response = response
        self.calls: list[dict[str, Any]] = []

    async def ainvoke(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(payload)
        return self._response


# ── mock fallbacks all carry the degraded-data flag ──────────────────────────

def test_all_mocks_flagged_as_mock_sandbox() -> None:
    for mock in (_mock_mpesa(), _mock_fx_rates(), _mock_credit_score(), _mock_kra_status()):
        assert mock["data_source"] == "mock_sandbox"


# ── M-Pesa: no credentials → mock (the silent-degradation path) ───────────────

@pytest.mark.asyncio
async def test_mpesa_without_credentials_returns_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(i_integrator.settings, "MPESA_CONSUMER_KEY", "")
    monkeypatch.setattr(i_integrator.settings, "MPESA_CONSUMER_SECRET", "")
    caller = _FakeCaller({"status_code": 200, "data": {}})
    result = await _fetch_mpesa_data(caller)
    assert result["data_source"] == "mock_sandbox"
    # Token short-circuits on missing creds — the transactions call never fires.
    assert caller.calls == []


@pytest.mark.asyncio
async def test_mpesa_live_success_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(i_integrator.settings, "MPESA_CONSUMER_KEY", "k")
    monkeypatch.setattr(i_integrator.settings, "MPESA_CONSUMER_SECRET", "s")

    class _SeqCaller:
        async def ainvoke(self, payload: dict[str, Any]) -> dict[str, Any]:
            if "oauth" in payload["url"]:
                return {"status_code": 200, "data": {"access_token": "tok"}}
            return {"status_code": 200, "data": {"balance": 1}}

    result = await _fetch_mpesa_data(_SeqCaller())
    assert result["source"] == "mpesa_live"
    assert "data_source" not in result  # live data is not flagged as mock


@pytest.mark.asyncio
async def test_mpesa_non_200_falls_back_to_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(i_integrator.settings, "MPESA_CONSUMER_KEY", "k")
    monkeypatch.setattr(i_integrator.settings, "MPESA_CONSUMER_SECRET", "s")

    class _SeqCaller:
        async def ainvoke(self, payload: dict[str, Any]) -> dict[str, Any]:
            if "oauth" in payload["url"]:
                return {"status_code": 200, "data": {"access_token": "tok"}}
            return {"status_code": 503, "data": None}

    result = await _fetch_mpesa_data(_SeqCaller())
    assert result["data_source"] == "mock_sandbox"


# ── CBK FX: no key → mock; key + 200 → live rates ─────────────────────────────

@pytest.mark.asyncio
async def test_fx_without_key_returns_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(i_integrator.settings, "CBK_FX_API_KEY", "")
    result = await _fetch_cbk_fx(_FakeCaller({"status_code": 200, "data": {}}))
    assert result["data_source"] == "mock_sandbox"


@pytest.mark.asyncio
async def test_fx_live_rates_parsed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(i_integrator.settings, "CBK_FX_API_KEY", "key")
    caller = _FakeCaller(
        {"status_code": 200, "data": {"rates": {"USD": 130.0, "EUR": 141.0, "GBP": 165.0}}}
    )
    result = await _fetch_cbk_fx(caller)
    assert result["source"] == "cbk_live"
    assert result["USD_KES"] == 130.0


# ── FX normaliser ─────────────────────────────────────────────────────────────

def test_normalise_kes_is_passthrough() -> None:
    assert _normalise_to_kes(1000.0, "KES", {"USD_KES": 130.0}) == 1000.0


def test_normalise_converts_with_rate() -> None:
    assert _normalise_to_kes(10.0, "USD", {"USD_KES": 130.0}) == 1300.0


def test_normalise_unknown_currency_passthrough() -> None:
    # No matching rate key → return the amount unchanged rather than guess.
    assert _normalise_to_kes(10.0, "JPY", {"USD_KES": 130.0}) == 10.0
