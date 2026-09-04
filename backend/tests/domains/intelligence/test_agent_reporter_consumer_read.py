"""A2A consumer-read — Agent G folds upstream forecast/audit outputs when present.

Two flows, one node:
  * single-agent (no upstream in context) → G is self-contained, consumes nothing;
  * planner (forecast + audit_result present) → G reads them, feeds the narrative
    prompt, records provenance, and surfaces them as findings.

Hermetic: DB tuning + cash-flow fetch, Gemini narrative, and the PDF/Excel
exporters are all mocked; the deterministic score core runs for real.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from src.domains.intelligence.agents.g_reporter import make_g_reporter_node

_LEDGER = {
    "months": ["2026-01", "2026-02", "2026-03", "2026-04"],
    "monthly_inflows": [100.0, 110.0, 120.0, 130.0],
    "monthly_outflows": [60.0, 62.0, 64.0, 66.0],
}
_FORECAST = {
    "current_balance": 250000.0,
    "regime": {"regime": "Stress", "advisory_warnings": ["Tightening runway"]},
}
_AUDIT = {
    "tax_type": "VAT", "effective_tax_rate": 16.0,
    "compliance_flags": ["late_filing", "missing_pin"],
}


def _state(context: dict[str, Any]) -> dict[str, Any]:
    return {
        "messages": [], "gen_ui_payloads": [], "error_messages": [], "handoffs": [],
        "next": "", "context": context, "session_id": "s1", "user_id": None,
        "mode": "insights",
    }


async def _run(context: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Run the node with all IO mocked; return (result, captured narrative prompts)."""
    prompts: list[str] = []

    async def _fake_narrative(prompt: str, *a: Any, **k: Any) -> str:
        prompts.append(prompt)
        return "Solid position; keep OpEx tight."

    node = make_g_reporter_node()
    with patch(
        "src.domains.intelligence.agents.g_reporter.refresh_agent_tuning_from_db",
        new=AsyncMock(return_value=None),
    ), patch(
        "src.domains.intelligence.services.bankability_service.generate_text_content",
        new=_fake_narrative,
    ), patch(
        "src.domains.intelligence.services.bankability_service._generate_pdf_report",
        return_value=b"",
    ), patch(
        "src.domains.intelligence.services.bankability_service._generate_forecast_excel",
        return_value=b"",
    ):
        result = await node(_state(context))
    return result, prompts


@pytest.mark.asyncio
async def test_single_agent_flow_consumes_nothing() -> None:
    result, prompts = await _run({"raw_ledger_data": _LEDGER})
    assert result["context"]["credit_forecast"]["consumed_upstream"] == []
    assert "upstream_agent_signals" not in prompts[0]


@pytest.mark.asyncio
async def test_planner_flow_reads_forecast_and_audit() -> None:
    result, prompts = await _run(
        {"raw_ledger_data": _LEDGER, "forecast": _FORECAST, "audit_result": _AUDIT}
    )
    ctx = result["context"]
    # Consumer-read must NOT introduce a new owned key — provenance lives *inside*
    # credit_forecast, so the minimal-diff return stays within G's write_keys.
    from src.domains.intelligence.agent_registry import write_keys
    assert set(ctx) <= write_keys("G")
    # Provenance recorded (within G's own credit_forecast key — no new owned key).
    assert ctx["credit_forecast"]["consumed_upstream"] == ["forecast", "audit_result"]
    # Upstream signals were injected into the narrative prompt.
    assert "upstream_agent_signals" in prompts[0]
    assert "Stress" in prompts[0] and "late_filing" in prompts[0]
    # And surfaced as GenUI findings.
    findings = ctx["credit_strategy_result"]  # AgentGOutput dump has no findings…
    assert findings["risk_tier"] in {"LOW", "MEDIUM", "HIGH"}
    payload = result["gen_ui_payloads"][0]
    metrics = {f["metric"] for f in payload.props["findings"]}
    assert {"Cash Regime", "Tax Flags"} <= metrics


@pytest.mark.asyncio
async def test_partial_upstream_only_forecast() -> None:
    result, prompts = await _run({"raw_ledger_data": _LEDGER, "forecast": _FORECAST})
    assert result["context"]["credit_forecast"]["consumed_upstream"] == ["forecast"]
    metrics = {
        f["metric"] for f in result["gen_ui_payloads"][0].props["findings"]
    }
    assert "Cash Regime" in metrics and "Tax Flags" not in metrics
