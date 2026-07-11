"""
Agent D — Cash-Flow Forecaster.

Agentic Hybrid Strategy for African SME volatility and data sparsity:

  1. Quantitative Baseline  — Holt-Winters exponential smoothing (statsmodels)
     fitted on up to 12 months of daily net cash-flow, projected 30 days forward.
     Invoice due-date amounts are overlaid as known future outflows.

  2. Semantic Regime Detector — the model evaluates the HW baseline, recent variance,
     and upcoming liabilities to classify the business into one of five financial
     regimes (Boom / Normal / Stress / Liquidity Crunch / Recovery) and generates
     actionable advisory warnings calibrated for Kenyan SMEs.

  3. Text-to-SQL CoVe — When context["text_to_sql_query"] is set, a three-step
     Chain-of-Verification workflow (Drafter → Explainer → Auditor) generates,
     translates, and audits a PostgreSQL query before executing it through the
     read-only sql_executor, writing results to context["sql_result"].

Writes context["forecast"] (CashFlowForecast) and optionally context["sql_result"]
(CoVeSQLQuery) before returning to the Supervisor node.
"""
from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from typing import Any

import numpy as np
import structlog
from langchain_core.messages import AIMessage
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.domains.intelligence.llm_client import generate_structured_content
from src.domains.intelligence.prompts.d_forecaster import (
    FORECASTER_COVE_AUDITOR_SYSTEM,
    FORECASTER_COVE_DRAFTER_SYSTEM,
    FORECASTER_COVE_EXPLAINER_SYSTEM,
    FORECASTER_REGIME_SYSTEM,
)
from src.domains.intelligence.schemas import (
    CashFlowForecast,
    CompositeGenUIPayload,
    CoVeSQLQuery,
    ForecastDataPoint,
    KeyFinding,
    OrchestratorState,
    RegimeAnalysis,
)
from src.domains.intelligence.tools.sql_executor import execute_readonly_sql
from src.infrastructure.database.postgres import AsyncSessionLocal

logger = structlog.get_logger(__name__)

_FORECAST_HORIZON = 30  # days


def _estimate_runway(balance: float, daily_flows: list[float]) -> str:
    """Estimate days/months until cash balance hits zero from daily forecast flows."""
    running = balance
    for i, flow in enumerate(daily_flows):
        running += flow
        if running <= 0:
            days = i + 1
            return f"{days // 30} Months" if days >= 60 else f"{days} Days"
    # Balance stays positive through forecast — try to extrapolate
    avg_daily = sum(daily_flows) / max(len(daily_flows), 1)
    if avg_daily >= 0:
        return ">30 Days"
    extra = int(running / max(-avg_daily, 0.01))
    total = len(daily_flows) + extra
    return f"{total // 30} Months" if total >= 60 else f"{total} Days"


# ---------------------------------------------------------------------------
# Private CoVe structured-output schemas
# ---------------------------------------------------------------------------

class _CoVeDraftExplain(BaseModel):
    # Drafter + Explainer folded into one structured call (Sprint 3: 3 LLM calls → 2).
    sql_query: str
    intent_summary: str
    plain_english: str


class _CoVeAudit(BaseModel):
    intent_preserved: bool
    confidence: float      # 0.0–1.0
    issues: list[str]


# ---------------------------------------------------------------------------
# Data-fetch helpers
# ---------------------------------------------------------------------------

async def _fetch_daily_cashflow(
    session: AsyncSession,
) -> list[tuple[date, float]]:
    """Pull 12 months of daily net cash-flow (credits minus debits) from ledger_entries."""
    sql = text("""
        SELECT
            date_trunc('day', created_at AT TIME ZONE 'Africa/Nairobi')::date AS day,
            SUM(
                CASE WHEN transaction_type = 'CREDIT' THEN amount::float
                     ELSE -amount::float END
            ) AS net_flow
        FROM ledger_entries
        WHERE created_at >= NOW() - INTERVAL '12 months'
        GROUP BY day
        ORDER BY day ASC
    """)
    result = await session.execute(sql)
    return [(row[0], float(row[1])) for row in result.fetchall()]


async def _fetch_current_balance(session: AsyncSession) -> float:
    """Sum all ledger credits minus debits to derive the running account balance."""
    sql = text("""
        SELECT COALESCE(
            SUM(CASE WHEN transaction_type = 'CREDIT' THEN amount::float
                     ELSE -amount::float END),
            0.0
        )
        FROM ledger_entries
    """)
    result = await session.execute(sql)
    return float(result.scalar() or 0.0)


async def _fetch_upcoming_invoices(
    session: AsyncSession,
    horizon_days: int,
) -> list[dict[str, Any]]:
    """Return open invoices due within the forecast horizon, grouped by due date."""
    sql = text("""
        SELECT
            due_date::date           AS due_date,
            SUM(balance_due::float)  AS total_due
        FROM invoices
        WHERE status IN ('SENT', 'OVERDUE', 'PARTIALLY_PAID')
          AND due_date BETWEEN NOW() AND NOW() + CAST(:interval AS interval)
          AND balance_due > 0
        GROUP BY due_date::date
        ORDER BY due_date ASC
    """)
    result = await session.execute(sql, {"interval": f"{horizon_days} days"})
    return [{"date": str(row[0]), "amount": float(row[1])} for row in result.fetchall()]


# ---------------------------------------------------------------------------
# Holt-Winters model
# ---------------------------------------------------------------------------

def _fit_holtwinters(
    daily_flows: list[tuple[Any, float]],
    horizon: int = _FORECAST_HORIZON,
) -> tuple[list[float], str]:
    """
    Fit a Holt-Winters ExponentialSmoothing model and return (forecast, model_name).

    Adaptive strategy based on available data:
      < 3 points  → flat forecast (last observed value)
      3–13 points → additive trend only (no seasonal)
      14+ points  → additive trend + additive weekly seasonality (period = 7)
    """
    # statsmodels import is deferred to avoid heavy startup cost for other agents
    from statsmodels.tsa.holtwinters import ExponentialSmoothing  # noqa: PLC0415

    values = np.array([v for _, v in daily_flows], dtype=float)
    n = len(values)

    if n < 3:
        last = float(values[-1]) if n > 0 else 0.0
        return [last] * horizon, "flat"

    use_seasonal = n >= 14
    try:
        model = ExponentialSmoothing(
            values,
            trend="add",
            seasonal="add" if use_seasonal else None,
            seasonal_periods=7 if use_seasonal else None,
            initialization_method="estimated",
        )
        fit = model.fit(optimized=True, remove_bias=True)
        forecast = fit.forecast(horizon).tolist()
        model_name = "holt_winters_seasonal" if use_seasonal else "holt_winters_trend"
    except Exception as exc:
        logger.warning("d_forecaster: HW model failed, using linear trend", error=str(exc))
        trend = float((values[-1] - values[0]) / n) if n >= 2 else 0.0
        forecast = [float(values[-1]) + trend * (i + 1) for i in range(horizon)]
        model_name = "linear_trend"

    return forecast, model_name


# ---------------------------------------------------------------------------
# Regime Detector
# ---------------------------------------------------------------------------

async def _detect_regime(
    current_balance: float,
    forecast_flows: list[float],
    daily_flows: list[tuple[Any, float]],
    upcoming_invoices: list[dict[str, Any]],
) -> RegimeAnalysis:
    recent = [v for _, v in daily_flows[-30:]] if daily_flows else []
    variance = float(np.std(recent)) if recent else 0.0
    mean_flow = float(np.mean(recent)) if recent else 0.0
    projected_30d = current_balance + sum(forecast_flows)
    total_due = sum(inv["amount"] for inv in upcoming_invoices)

    quantitative = {
        "current_balance_kes": round(current_balance, 2),
        "mean_daily_net_flow_kes": round(mean_flow, 2),
        "daily_flow_std_dev_kes": round(variance, 2),
        "projected_30d_balance_kes": round(projected_30d, 2),
        "total_upcoming_invoices_due_kes": round(total_due, 2),
        "num_upcoming_invoices": len(upcoming_invoices),
        "forecast_30d_trend": "positive" if sum(forecast_flows) > 0 else "negative",
        "historical_data_points": len(daily_flows),
    }

    prompt = (
        f"{FORECASTER_REGIME_SYSTEM}\n\n"
        "## Quantitative Summary\n"
        f"{json.dumps(quantitative, indent=2)}\n\n"
        "## 30-Day Baseline Forecast (daily net flows, KES)\n"
        f"{json.dumps([round(f, 2) for f in forecast_flows], indent=2)}\n\n"
        "## Upcoming Invoice Due Dates\n"
        f"{json.dumps(upcoming_invoices[:15], indent=2)}\n\n"
        "Determine the financial regime and provide risk factors, "
        "advisory warnings, and a narrative."
    )

    return await generate_structured_content(prompt, RegimeAnalysis, temperature=0.2)


# ---------------------------------------------------------------------------
# Chain-of-Verification Text-to-SQL
# ---------------------------------------------------------------------------

async def _cove_text_to_sql(user_query: str, *, verify: bool = True) -> CoVeSQLQuery:
    """
    Chain-of-Verification Text-to-SQL, cost-tuned (Sprint 3).

      Step 1 (1 call) — combined Drafter+Explainer: writes the PostgreSQL SELECT
      *and* its plain-English translation in one structured response.
      Step 2 (1 call, only when ``verify``) — Auditor: verifies the translation
      matches the original intent; execution requires intent_preserved and
      confidence ≥ 0.70.

    So the default verified path is **2 LLM calls (was 3)**; passing
    ``verify=False`` (ctx["cove_verify"]=false) drops the audit to **1 call** and
    relies on the read-only SQL guard (regex + sqlglot AST + LIMIT clamp) as the
    safety net. In all cases the query runs under the ``finguard_readonly`` role.
    """
    # ── Step 1: Draft + Explain (single call) ─────────────────────────────────
    draft_prompt = (
        f"{FORECASTER_COVE_DRAFTER_SYSTEM}\n\n{FORECASTER_COVE_EXPLAINER_SYSTEM}\n\n"
        f"User question: {user_query}\n\n"
        "Write the PostgreSQL SELECT query, a one-line intent_summary, and a "
        "one-paragraph plain_english description of what it retrieves."
    )
    draft = await generate_structured_content(draft_prompt, _CoVeDraftExplain, temperature=0.0)

    # ── Step 2: Audit (optional) ──────────────────────────────────────────────
    approved = True
    audit_notes = "CoVe verification skipped (cove_verify=false)."
    if verify:
        audit_prompt = (
            f"{FORECASTER_COVE_AUDITOR_SYSTEM}\n\n"
            f"User Question: {user_query}\n\n"
            f"SQL Query:\n{draft.sql_query}\n\n"
            f"Plain-English Translation:\n{draft.plain_english}\n\n"
            "Verify correctness, safety, and completeness. "
            "Set intent_preserved = true only if the SQL correctly answers the question."
        )
        audit = await generate_structured_content(audit_prompt, _CoVeAudit, temperature=0.0)
        approved = audit.intent_preserved and audit.confidence >= 0.70
        audit_notes = "; ".join(audit.issues) if audit.issues else "No issues found."

    # Deterministic gate (independent of the LLM audit): only ever run a single
    # read-only SELECT/CTE. A drafted statement that isn't one is rejected no
    # matter what the auditor said — the LLM verdict is never the only gate.
    if not draft.sql_query.strip().lower().startswith(("select", "with")):
        approved = False
        audit_notes = f"Rejected: not a read-only SELECT statement. {audit_notes}"

    # ── Execute if approved ────────────────────────────────────────────────────
    results: list[dict[str, Any]] | None = None
    if approved:
        try:
            results = await execute_readonly_sql(draft.sql_query)
            logger.info(
                "d_forecaster: CoVe SQL executed",
                rows=len(results),
                query_summary=draft.intent_summary,
                verified=verify,
            )
        except Exception as exc:
            logger.warning("d_forecaster: CoVe SQL execution failed", error=str(exc))

    return CoVeSQLQuery(
        original_query=user_query,
        sql=draft.sql_query,
        explanation=draft.plain_english,
        audit_passed=approved,
        audit_notes=audit_notes,
        results=results,
    )


# ---------------------------------------------------------------------------
# LangGraph node
# ---------------------------------------------------------------------------

def make_d_forecaster_node(llm: Any = None) -> Any:  # llm kept for signature compatibility
    async def d_forecaster_node(state: OrchestratorState) -> dict[str, Any]:
        ctx = dict(state["context"])
        horizon = int(ctx.get("forecast_horizon_days", _FORECAST_HORIZON))
        text_to_sql_query: str | None = ctx.get("text_to_sql_query")

        async with AsyncSessionLocal() as session:
            # ── 1. Historical data ────────────────────────────────────────────
            daily_flows = await _fetch_daily_cashflow(session)
            current_balance = await _fetch_current_balance(session)
            upcoming_invoices = await _fetch_upcoming_invoices(session, horizon)

        # ── 2. Holt-Winters forecast ──────────────────────────────────────────
        if daily_flows:
            raw_forecast, model_name = _fit_holtwinters(daily_flows, horizon)
        else:
            raw_forecast = [0.0] * horizon
            model_name = "no_data"

        # ── 3. Invoice overlay → projected balance ────────────────────────────
        today = date.today()
        invoice_map = {inv["date"]: inv["amount"] for inv in upcoming_invoices}
        data_points: list[ForecastDataPoint] = []
        running_balance = current_balance

        for i, net_flow in enumerate(raw_forecast):
            day_str = (today + timedelta(days=i + 1)).isoformat()
            scheduled = invoice_map.get(day_str, 0.0)
            running_balance += net_flow - scheduled
            data_points.append(
                ForecastDataPoint(
                    date=day_str,
                    baseline_net_flow=round(net_flow, 2),
                    scheduled_payment=round(scheduled, 2),
                    projected_balance=round(running_balance, 2),
                )
            )

        # ── 4. Semantic Regime Detector ───────────────────────────────────────
        try:
            regime = await _detect_regime(
                current_balance, raw_forecast, daily_flows, upcoming_invoices
            )
        except Exception as exc:
            logger.error("d_forecaster: regime detection failed", error=str(exc))
            regime = RegimeAnalysis(
                regime="Normal",
                confidence=0.5,
                risk_factors=["Regime detection unavailable — review data manually."],
                advisory_warnings=["Monitor cash flow manually until regime analysis recovers."],
                narrative=(
                    "Automated regime analysis failed. "
                    "The quantitative baseline is still valid. "
                    "Please review your cash position manually."
                ),
            )

        # ── 5. CoVe Text-to-SQL (opt-in: presence of the query enables it) ────
        # cove_verify (default True) toggles the audit step: True → 2 LLM calls,
        # False → 1 call trusting the read-only SQL guard.
        sql_result_dump: dict[str, Any] | None = None
        if text_to_sql_query:
            verify = bool(ctx.get("cove_verify", True))
            try:
                sql_result = await _cove_text_to_sql(text_to_sql_query, verify=verify)
                sql_result_dump = sql_result.model_dump()
            except Exception as exc:
                logger.error("d_forecaster: CoVe workflow failed", error=str(exc))

        # ── 6. Write forecast to context ──────────────────────────────────────
        forecast = CashFlowForecast(
            horizon_days=horizon,
            current_balance=round(current_balance, 2),
            data_points=data_points,
            regime=regime,
            model_used=model_name,
            generated_at=datetime.now(UTC).isoformat(),
        )

        projected_final = data_points[-1].projected_balance if data_points else current_balance
        summary = (
            f"[d_forecaster] {horizon}-day forecast generated ({model_name}). "
            f"Regime: {regime.regime} (confidence {regime.confidence:.0%}). "
            f"Current: KES {current_balance:,.0f} → "
            f"Projected: KES {projected_final:,.0f}."
        )
        if ctx.get("sql_result"):
            sql_res = ctx["sql_result"]
            summary += (
                f" SQL query {'executed' if sql_res.get('audit_passed') else 'failed audit'}."
            )

        # ── 7. Emit CompositeGenUIPayload ─────────────────────────────────────
        runway = _estimate_runway(current_balance, raw_forecast)
        findings: list[KeyFinding] = [
            KeyFinding(metric="Regime", value=regime.regime),
            KeyFinding(metric="Confidence", value=f"{regime.confidence:.0%}"),
            KeyFinding(metric="30d Balance", value=f"KES {projected_final:,.0f}"),
            KeyFinding(metric="Runway", value=runway),
        ]
        for rf in regime.risk_factors[:2]:
            findings.append(KeyFinding(metric="Risk", value=rf[:100]))

        composite = CompositeGenUIPayload(
            component_id="CashFlowChart",
            props={
                "current_balance": round(current_balance, 2),
                "data_points": [dp.model_dump() for dp in data_points],
                "regime": regime.model_dump(),
            },
            findings=findings,
            fallback_text=(
                f"Cash flow forecast: {regime.regime} regime. "
                f"Current KES {current_balance:,.0f} → projected KES {projected_final:,.0f} "
                f"in {horizon} days. Runway: {runway}."
            ),
        )

        ctx_update: dict[str, Any] = {"forecast": forecast.model_dump()}
        if sql_result_dump is not None:
            ctx_update["sql_result"] = sql_result_dump
        return {
            "messages": [AIMessage(content=summary, name="d_forecaster")],
            "context": ctx_update,
            "gen_ui_payloads": [composite.to_gen_ui_payload()],
        }

    return d_forecaster_node
