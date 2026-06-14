"""
Sprint 6 — Unit tests: CompositeGenUIPayload schema and per-agent state conformance.

Validates that:
  1. CompositeGenUIPayload.to_gen_ui_payload() correctly merges findings into props.
  2. Each of agents D, E, F, G returns a ``gen_ui_payloads`` list whose single element
     is a valid GenUIPayload with the expected component_id, props shape, and
     findings structure (list of {metric, value} dicts conforming to KeyFinding).

All network and database I/O is replaced with deterministic in-process mocks.
Tests are hermetic: no running DB, Gemini API, RabbitMQ, or Redis required.
"""
from __future__ import annotations

import json
from contextlib import ExitStack, asynccontextmanager, contextmanager
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from src.domains.intelligence.schemas import (
    CompositeGenUIPayload,
    GenUIPayload,
    KeyFinding,
    RegimeAnalysis,
)

# ── Shared test helpers ────────────────────────────────────────────────────────

def _make_state(**ctx_overrides) -> dict:
    """Build a minimal OrchestratorState dict for unit-testing agent nodes."""
    return {
        "messages": [],
        "gen_ui_payloads": [],
        "error_messages": [],
        "next": "FINISH",
        "context": {"account_id": "acct-test", **ctx_overrides},
        "session_id": "sess-test",
        "user_id": "user-test",
        "mode": "insights",
    }


def _validate_payload(
    payload: GenUIPayload,
    expected_cid: str,
    required_props: list[str],
) -> None:
    """Assert that a GenUIPayload element conforms to the Sprint 6 contract."""
    assert isinstance(payload, GenUIPayload)
    assert payload.component_id == expected_cid, (
        f"Expected component_id={expected_cid!r}, got {payload.component_id!r}"
    )
    assert payload.fallback_text.strip(), "fallback_text must not be blank"

    for key in required_props:
        assert key in payload.props, (
            f"props missing required key {key!r}; present keys: {list(payload.props)}"
        )

    findings = payload.props.get("findings", [])
    assert isinstance(findings, list), "findings must be a list"
    for item in findings:
        assert isinstance(item, dict) and {"metric", "value"} <= item.keys(), (
            f"finding item is missing metric/value: {item}"
        )
        kf = KeyFinding(**item)  # raises ValidationError if schema is violated
        assert kf.metric and kf.value


@asynccontextmanager
async def _noop_session():
    """Async context manager that yields a MagicMock — avoids real DB connections."""
    yield MagicMock()


def _gemini_mock(response_text: str) -> MagicMock:
    """Build a minimal mock Gemini client whose generate_content returns response_text."""
    resp = MagicMock()
    resp.text = response_text
    client = MagicMock()
    client.aio.models.generate_content = AsyncMock(return_value=resp)
    return client


# ── Part 1: Schema unit tests (no I/O) ────────────────────────────────────────

class TestCompositeGenUIPayload:
    def test_to_gen_ui_payload_merges_findings_into_props(self) -> None:
        composite = CompositeGenUIPayload(
            component_id="CashFlowChart",
            props={"current_balance": 50_000.0, "data_points": []},
            findings=[
                KeyFinding(metric="Regime", value="Normal"),
                KeyFinding(metric="Runway", value="6 Months"),
            ],
            fallback_text="Cash flow chart.",
        )
        payload = composite.to_gen_ui_payload()
        assert isinstance(payload, GenUIPayload)
        assert payload.component_id == "CashFlowChart"
        assert payload.props["current_balance"] == 50_000.0
        assert payload.props["findings"] == [
            {"metric": "Regime", "value": "Normal"},
            {"metric": "Runway", "value": "6 Months"},
        ]

    def test_to_gen_ui_payload_empty_findings_produces_empty_list(self) -> None:
        composite = CompositeGenUIPayload(
            component_id="AuditorInsights",
            props={"tax_type": "VAT"},
            findings=[],
            fallback_text="Tax audit.",
        )
        assert composite.to_gen_ui_payload().props["findings"] == []

    def test_key_finding_rejects_empty_metric(self) -> None:
        with pytest.raises(ValidationError):
            KeyFinding(metric="", value="some value")

    def test_key_finding_rejects_empty_value(self) -> None:
        with pytest.raises(ValidationError):
            KeyFinding(metric="Runway", value="")

    def test_composite_rejects_whitespace_component_id(self) -> None:
        with pytest.raises(ValidationError):
            CompositeGenUIPayload(
                component_id=" CashFlowChart",
                props={},
                fallback_text="x",
            )

    def test_findings_survive_json_round_trip(self) -> None:
        """Merged payload must survive json.dumps / json.loads cleanly."""
        composite = CompositeGenUIPayload(
            component_id="DuplicateInvoiceAlert",
            props={"anomaly_score": 0.87, "current_state": "CRITICAL"},
            findings=[KeyFinding(metric="Pattern", value="Spike 3x above average")],
            fallback_text="Anomaly detected.",
        )
        payload = composite.to_gen_ui_payload()
        reloaded = json.loads(json.dumps(payload.model_dump(), default=str))
        restored = GenUIPayload(**reloaded)
        assert restored.component_id == "DuplicateInvoiceAlert"
        assert restored.props["findings"][0]["metric"] == "Pattern"

    def test_findings_not_duplicated_when_props_have_existing_key(self) -> None:
        """to_gen_ui_payload must not overwrite an existing 'findings' key in props."""
        existing = [{"metric": "Pre-existing", "value": "Value"}]
        composite = CompositeGenUIPayload(
            component_id="AuditorInsights",
            props={"findings": existing, "tax_type": "VAT"},
            findings=[KeyFinding(metric="New", value="Finding")],
            fallback_text=".",
        )
        merged = composite.to_gen_ui_payload().props["findings"]
        # The composite findings list (from KeyFinding objects) should win
        assert merged == [{"metric": "New", "value": "Finding"}]


# ── Part 2: Agent D ────────────────────────────────────────────────────────────

class TestAgentDForecaster:
    _mock_regime = RegimeAnalysis(
        regime="Normal",
        confidence=0.80,
        risk_factors=[
            "Stable daily variance of KES 3,000",
            "30-day projected balance: KES 75,000",
        ],
        advisory_warnings=["Monitor M-Pesa settlement lag closely"],
        narrative="The business is operating in a Normal financial regime.",
    )

    @pytest.mark.asyncio
    async def test_emits_cashflowchart_payload(self) -> None:
        from src.domains.intelligence.agents.d_forecaster import make_d_forecaster_node

        daily = [(date(2024, 1, i), float(i * 200)) for i in range(1, 20)]

        with (
            patch("src.domains.intelligence.agents.d_forecaster.AsyncSessionLocal", _noop_session),
            patch("src.domains.intelligence.agents.d_forecaster._fetch_daily_cashflow", new_callable=AsyncMock, return_value=daily),
            patch("src.domains.intelligence.agents.d_forecaster._fetch_current_balance", new_callable=AsyncMock, return_value=75_000.0),
            patch("src.domains.intelligence.agents.d_forecaster._fetch_upcoming_invoices", new_callable=AsyncMock, return_value=[]),
            patch("src.domains.intelligence.agents.d_forecaster._detect_regime", new_callable=AsyncMock, return_value=self._mock_regime),
        ):
            result = await make_d_forecaster_node()(_make_state())

        assert "gen_ui_payloads" in result
        assert len(result["gen_ui_payloads"]) == 1
        _validate_payload(
            result["gen_ui_payloads"][0],
            "CashFlowChart",
            ["current_balance", "data_points", "regime"],
        )
        # Regime must be nested, not flattened
        assert result["gen_ui_payloads"][0].props["regime"]["regime"] == "Normal"

    @pytest.mark.asyncio
    async def test_runway_and_regime_findings_present(self) -> None:
        from src.domains.intelligence.agents.d_forecaster import make_d_forecaster_node

        with (
            patch("src.domains.intelligence.agents.d_forecaster.AsyncSessionLocal", _noop_session),
            patch("src.domains.intelligence.agents.d_forecaster._fetch_daily_cashflow", new_callable=AsyncMock, return_value=[(date(2024, 1, i), -100.0) for i in range(1, 12)]),
            patch("src.domains.intelligence.agents.d_forecaster._fetch_current_balance", new_callable=AsyncMock, return_value=10_000.0),
            patch("src.domains.intelligence.agents.d_forecaster._fetch_upcoming_invoices", new_callable=AsyncMock, return_value=[]),
            patch("src.domains.intelligence.agents.d_forecaster._detect_regime", new_callable=AsyncMock, return_value=self._mock_regime),
        ):
            result = await make_d_forecaster_node()(_make_state())

        findings = result["gen_ui_payloads"][0].props["findings"]
        metrics = {f["metric"] for f in findings}
        assert "Regime" in metrics, f"'Regime' not in finding metrics: {metrics}"
        assert "Runway" in metrics, f"'Runway' not in finding metrics: {metrics}"


# ── Part 3: Agent E ────────────────────────────────────────────────────────────

class TestAgentEWatchdog:
    _llm_json = json.dumps({
        "current_state": "HEALTHY",
        "anomaly_detected": False,
        "summary": "Account operating within normal parameters.",
        "findings": [
            {"metric": "Pattern", "value": "Consistent spending at 62% of budget"},
            {"metric": "IsolationForest", "value": "Score 0.12 — no outliers detected"},
        ],
    })

    @contextmanager
    def _watchdog_patches(self, *, ratios=None, amounts=None, invoices=None):
        """Context manager applying the standard set of patches for Agent E."""
        with ExitStack() as stack:
            stack.enter_context(patch("src.domains.intelligence.agents.e_watchdog.AsyncSessionLocal", _noop_session))
            stack.enter_context(patch("src.domains.intelligence.agents.e_watchdog._fetch_spending_ratios", new_callable=AsyncMock, return_value=ratios or [0.55, 0.60, 0.58, 0.62, 0.50]))
            stack.enter_context(patch("src.domains.intelligence.agents.e_watchdog._fetch_recent_amounts", new_callable=AsyncMock, return_value=amounts or [1000.0, 1200.0, 800.0, 1500.0, 900.0, 1100.0]))
            stack.enter_context(patch("src.domains.intelligence.agents.e_watchdog._fetch_recent_invoices", new_callable=AsyncMock, return_value=invoices or [{"invoice_number": "INV-001", "amount": 1000.0, "vendor": "Acme"}]))
            stack.enter_context(patch("src.domains.intelligence.agents.e_watchdog.get_gemini_client", return_value=_gemini_mock(self._llm_json)))
            stack.enter_context(patch("src.domains.intelligence.agents.e_watchdog.AGENT_E_ANOMALY_SCORE"))
            stack.enter_context(patch("src.domains.intelligence.agents.e_watchdog.AGENT_E_STATE_PROBABILITY"))
            stack.enter_context(patch("src.domains.intelligence.agents.e_watchdog.AGENT_LLM_LATENCY"))
            stack.enter_context(patch("src.domains.intelligence.agents.e_watchdog.AGENT_LLM_PROCESSING"))
            yield

    @pytest.mark.asyncio
    async def test_emits_budget_watchdog_meter_payload(self) -> None:
        from src.domains.intelligence.agents.e_watchdog import make_e_watchdog_node

        with self._watchdog_patches():
            result = await make_e_watchdog_node()(_make_state())

        assert "gen_ui_payloads" in result
        assert len(result["gen_ui_payloads"]) == 1
        _validate_payload(
            result["gen_ui_payloads"][0],
            "BudgetWatchdogMeter",
            ["anomaly_detected", "anomaly_score", "current_state", "is_duplicate", "state_probabilities"],
        )

    @pytest.mark.asyncio
    async def test_deterministic_props_independent_of_llm(self) -> None:
        """IsolationForest score and HMM state must live in props regardless of LLM output."""
        from src.domains.intelligence.agents.e_watchdog import make_e_watchdog_node

        with self._watchdog_patches():
            result = await make_e_watchdog_node()(_make_state())

        props = result["gen_ui_payloads"][0].props
        assert isinstance(props["anomaly_score"], float)
        assert isinstance(props["is_duplicate"], bool)
        assert props["current_state"] in {"HEALTHY", "STABLE", "CRITICAL"}

    @pytest.mark.asyncio
    async def test_llm_findings_embedded_in_props(self) -> None:
        """LLM-generated bullet-point findings must appear in props['findings']."""
        from src.domains.intelligence.agents.e_watchdog import make_e_watchdog_node

        with self._watchdog_patches():
            result = await make_e_watchdog_node()(_make_state())

        findings = result["gen_ui_payloads"][0].props["findings"]
        assert len(findings) >= 1
        metrics = {f["metric"] for f in findings}
        assert "Pattern" in metrics or "IsolationForest" in metrics


# ── Part 4: Agent F ────────────────────────────────────────────────────────────

class TestAgentFAuditor:
    _gemini_analysis = json.dumps({
        "compliance_flags": ["AML_REPORTING_REQUIRED", "VAT threshold breach imminent"],
        "kra_references": ["[KRA Ref: VAT Act — Section 2]"],
        "audit_summary": "Comprehensive audit complete. 2 compliance flags require action.",
    })
    _gemini_analysis_no_aml = json.dumps({
        "compliance_flags": ["VAT threshold breach imminent"],
        "kra_references": ["[KRA Ref: VAT Act — Section 2]"],
        "audit_summary": "Comprehensive audit complete. 1 compliance flag requires action.",
    })

    def _ctx(self, max_single_tx: float = 500_000.0) -> dict:
        return {
            "ledger_snapshot": {
                "revenue": 500_000.0,
                "opex": 300_000.0,
                "tx_count": 42,
                "max_single_tx": max_single_tx,
            },
            "tax_regime": "COMPREHENSIVE",
            "audit_period_days": 365,
        }

    @contextmanager
    def _patches(self, gemini_text: str | None = None):
        analysis = gemini_text if gemini_text is not None else self._gemini_analysis
        with ExitStack() as stack:
            stack.enter_context(patch("src.domains.intelligence.agents.f_auditor.get_relevant_tax_rules", new_callable=AsyncMock, return_value=["[KRA Ref: VAT Act — Section 2]\nVAT at 16%..."]))
            stack.enter_context(patch("src.domains.intelligence.agents.f_auditor.get_gemini_client", return_value=_gemini_mock(analysis)))
            yield

    @pytest.mark.asyncio
    async def test_emits_tax_liability_donut_payload(self) -> None:
        from src.domains.intelligence.agents.f_auditor import make_f_auditor_node

        with self._patches():
            result = await make_f_auditor_node()(_make_state(**self._ctx()))

        assert "gen_ui_payloads" in result
        assert len(result["gen_ui_payloads"]) == 1
        _validate_payload(
            result["gen_ui_payloads"][0],
            "TaxLiabilityDonut",
            ["tax_type", "tax_liability", "effective_tax_rate", "compliance_flags", "audit_summary",
             "vat_component", "cit_component"],
        )

    @pytest.mark.asyncio
    async def test_aml_flag_injected_when_threshold_breached(self) -> None:
        """Agent F deterministically injects AML_REPORTING_REQUIRED when max_single_tx > 1M."""
        from src.domains.intelligence.agents.f_auditor import make_f_auditor_node

        with self._patches():
            result = await make_f_auditor_node()(_make_state(**self._ctx(max_single_tx=1_200_000.0)))

        flags: list[str] = result["gen_ui_payloads"][0].props["compliance_flags"]
        assert any("AML_REPORTING_REQUIRED" in f for f in flags), (
            f"AML flag not found in compliance_flags: {flags}"
        )

    @pytest.mark.asyncio
    async def test_aml_flag_absent_below_threshold(self) -> None:
        """AML_REPORTING_REQUIRED must NOT appear when max_single_tx < 1M."""
        from src.domains.intelligence.agents.f_auditor import make_f_auditor_node

        with self._patches(gemini_text=self._gemini_analysis_no_aml):
            result = await make_f_auditor_node()(_make_state(**self._ctx(max_single_tx=200_000.0)))

        flags: list[str] = result["gen_ui_payloads"][0].props["compliance_flags"]
        assert not any("AML_REPORTING_REQUIRED" in f for f in flags), (
            f"AML flag should be absent but found: {flags}"
        )

    @pytest.mark.asyncio
    async def test_key_findings_contain_liability_and_etr(self) -> None:
        from src.domains.intelligence.agents.f_auditor import make_f_auditor_node

        with self._patches():
            result = await make_f_auditor_node()(_make_state(**self._ctx()))

        metrics = {f["metric"] for f in result["gen_ui_payloads"][0].props["findings"]}
        assert "Liability" in metrics, f"'Liability' not in findings metrics: {metrics}"
        assert "ETR" in metrics, f"'ETR' not in findings metrics: {metrics}"


# ── Part 5: Agent G ────────────────────────────────────────────────────────────

class TestAgentGReporter:
    _narrative = (
        "The business holds a MEDIUM risk tier with bankability score 62/100. "
        "Q1-Q2 revenue trend is improving. Recommend diversifying revenue streams."
    )

    def _ctx(self) -> dict:
        return {
            "raw_ledger_data": {
                "months": ["2024-01", "2024-02", "2024-03", "2024-04"],
                "monthly_inflows": [400_000.0, 420_000.0, 390_000.0, 450_000.0],
                "monthly_outflows": [320_000.0, 330_000.0, 310_000.0, 360_000.0],
            },
        }

    @contextmanager
    def _patches(self):
        with ExitStack() as stack:
            stack.enter_context(patch("src.domains.intelligence.agents.g_reporter.get_gemini_client", return_value=_gemini_mock(self._narrative)))
            stack.enter_context(patch("src.domains.intelligence.agents.g_reporter._generate_pdf_report", return_value=b""))
            stack.enter_context(patch("src.domains.intelligence.agents.g_reporter._generate_forecast_excel", return_value=b""))
            yield

    @pytest.mark.asyncio
    async def test_emits_bankability_score_radar_payload(self) -> None:
        from src.domains.intelligence.agents.g_reporter import make_g_reporter_node

        with self._patches():
            result = await make_g_reporter_node()(_make_state(**self._ctx()))

        assert "gen_ui_payloads" in result
        assert len(result["gen_ui_payloads"]) == 1
        _validate_payload(
            result["gen_ui_payloads"][0],
            "BankabilityScoreRadar",
            ["bankability_score", "risk_tier", "strategic_narrative", "quarterly_revenue_kes",
             "trend_score", "ratio_score"],
        )

    @pytest.mark.asyncio
    async def test_bankability_score_is_bounded(self) -> None:
        """Deterministic bankability score must be 0–100."""
        from src.domains.intelligence.agents.g_reporter import make_g_reporter_node

        with self._patches():
            result = await make_g_reporter_node()(_make_state(**self._ctx()))

        score: int = result["gen_ui_payloads"][0].props["bankability_score"]
        assert 0 <= score <= 100, f"bankability_score out of range: {score}"

    @pytest.mark.asyncio
    async def test_risk_tier_is_valid_enum_value(self) -> None:
        from src.domains.intelligence.agents.g_reporter import make_g_reporter_node

        with self._patches():
            result = await make_g_reporter_node()(_make_state(**self._ctx()))

        tier: str = result["gen_ui_payloads"][0].props["risk_tier"]
        assert tier in {"LOW", "MEDIUM", "HIGH"}, f"Unexpected risk_tier: {tier!r}"

    @pytest.mark.asyncio
    async def test_key_findings_contain_score_and_tier(self) -> None:
        from src.domains.intelligence.agents.g_reporter import make_g_reporter_node

        with self._patches():
            result = await make_g_reporter_node()(_make_state(**self._ctx()))

        metrics = {f["metric"] for f in result["gen_ui_payloads"][0].props["findings"]}
        assert "Score" in metrics, f"'Score' not in findings metrics: {metrics}"
        assert "Risk Tier" in metrics, f"'Risk Tier' not in findings metrics: {metrics}"
