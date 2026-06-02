"""
Agent G — Credit Strategist (Report Generator).

Pipeline:
  1. Load or fetch monthly cash-flow history (last 12 months) from the
     state context or PostgreSQL.
  2. Run deterministic Holt-Winters Exponential Smoothing via statsmodels
     to project revenue and OpEx for the next 4 quarters (12 months).
     Falls back to linear extrapolation when fewer than 4 data points exist.
  3. Compute a deterministic bankability score (0-100) and risk tier from
     the historical + forecast arrays — no LLM hallucination of numbers.
  4. Pass the computed figures to Gemini 2.5 Flash to write the
     strategic_narrative (executive text only; all numeric fields are
     pre-computed and passed as context).
  5. Assemble AgentGOutput and write to state["context"]["credit_strategy_result"].

Trigger: supervisor routes here when state["next"] == "g_reporter".
"""
from __future__ import annotations

import json
from typing import Any

import numpy as np
from langchain_core.messages import AIMessage
from sqlalchemy import text

from src.core.config import settings
from src.core.logging import logger
from src.domains.intelligence.llm_client import get_gemini_client
from src.domains.intelligence.schemas import AgentGOutput, OrchestratorState
from src.infrastructure.database.postgres import AsyncSessionLocal

# ── Forecasting ───────────────────────────────────────────────────────────────

def _forecast_series(historical: list[float], periods: int = 12) -> list[float]:
    """
    Project `periods` future values using Holt-Winters additive-trend smoothing.

    Guarantees non-negative forecasts.  Degrades gracefully:
    - < 4 points  → simple mean + linear trend extrapolation
    - statsmodels failure → last-value drift

    Never returns a negative forecast; values are clamped to 0.
    """
    n = len(historical)
    if n == 0:
        return [0.0] * periods

    arr = np.array(historical, dtype=float)

    if n < 4:
        mean = float(np.mean(arr))
        slope = float((arr[-1] - arr[0]) / max(n - 1, 1))
        return [max(0.0, round(mean + slope * (i + 1), 2)) for i in range(periods)]

    try:
        from statsmodels.tsa.holtwinters import ExponentialSmoothing

        model = ExponentialSmoothing(
            arr,
            trend="add",
            seasonal=None,
            initialization_method="estimated",
        ).fit(optimized=True)
        raw = model.forecast(periods)
        return [max(0.0, round(float(v), 2)) for v in raw]
    except Exception as exc:
        logger.warning("Agent G: ExponentialSmoothing failed", error=str(exc))
        # Last-value + slope drift fallback
        slope = float(arr[-1] - arr[max(n - 4, 0)]) / 3.0
        return [max(0.0, round(float(arr[-1]) + slope * (i + 1), 2)) for i in range(periods)]


# ── Bankability scoring ───────────────────────────────────────────────────────

def _compute_bankability_score(
    hist_revenue: list[float],
    hist_opex: list[float],
    fc_revenue: list[float],
    fc_opex: list[float],
) -> tuple[int, str]:
    """
    Deterministic bankability score (0-100) using four sub-components:

    Component                     Max pts  Signal
    ─────────────────────────────────────────────
    Revenue trend (3-month slope)    30    Positive growth adds score
    Expense ratio (opex / revenue)   30    Lower ratio = healthier margin
    Cash-flow consistency (CoV)      20    Lower CoV = more predictable
    Forecast solvency (quarters)     20    Quarters where revenue ≥ opex

    Risk tiers: LOW ≥ 75 | MEDIUM 45-74 | HIGH < 45
    """
    def safe_arr(lst: list[float]) -> np.ndarray:
        return np.array(lst, dtype=float) if lst else np.zeros(1)

    rev = safe_arr(hist_revenue)
    opx = safe_arr(hist_opex)

    # ── Component 1: Revenue trend (0-30) ────────────────────────────────
    if len(rev) >= 3:
        pct_change = (rev[-1] - rev[-3]) / max(rev[-3], 1.0)
        trend_score = int(min(30, max(0, pct_change * 60)))
    else:
        trend_score = 10

    # ── Component 2: Expense ratio (0-30) ────────────────────────────────
    mean_rev = float(np.mean(rev)) or 1.0
    mean_opx = float(np.mean(opx))
    ratio = mean_opx / mean_rev
    if ratio < 0.50:
        ratio_score = 30
    elif ratio < 0.65:
        ratio_score = 24
    elif ratio < 0.80:
        ratio_score = 16
    elif ratio < 0.95:
        ratio_score = 8
    elif ratio < 1.00:
        ratio_score = 3
    else:
        ratio_score = 0

    # ── Component 3: Cash-flow consistency (0-20) ─────────────────────────
    net = rev - opx
    if len(net) > 1:
        mean_net = float(np.mean(net))
        std_net = float(np.std(net))
        cov = std_net / max(abs(mean_net), 1.0)
        consistency_score = max(0, int(20 - cov * 12))
    else:
        consistency_score = 8

    # ── Component 4: Forecast solvency (0-20) ────────────────────────────
    if fc_revenue and fc_opex:
        quarters = min(len(fc_revenue), len(fc_opex))
        solvent = sum(
            1 for r, o in zip(fc_revenue[:quarters], fc_opex[:quarters], strict=False) if r >= o
        )
        runway_score = int((solvent / max(quarters, 1)) * 20)
    else:
        runway_score = 5

    total = trend_score + ratio_score + consistency_score + runway_score
    total = min(100, max(0, total))

    tier = "LOW" if total >= 75 else "MEDIUM" if total >= 45 else "HIGH"
    return total, tier


# ── Database helper ───────────────────────────────────────────────────────────

async def _fetch_monthly_cashflows() -> dict[str, Any]:
    """
    Aggregate ledger_entries into monthly revenue / opex buckets for the
    trailing 12 months, returning arrays oldest-first.
    """
    sql = text("""
        SELECT
            TO_CHAR(DATE_TRUNC('month', created_at), 'YYYY-MM') AS month,
            COALESCE(SUM(CASE WHEN transaction_type = 'credit'
                             THEN amount ELSE 0 END), 0) AS revenue,
            COALESCE(SUM(CASE WHEN transaction_type = 'debit'
                             THEN amount ELSE 0 END), 0) AS opex
        FROM ledger_entries
        WHERE created_at >= NOW() - INTERVAL '12 months'
        GROUP BY DATE_TRUNC('month', created_at)
        ORDER BY 1
    """)
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(sql)
            rows = result.fetchall()
        months = [row[0] for row in rows]
        revenues = [float(row[1] or 0) for row in rows]
        opex = [float(row[2] or 0) for row in rows]
        return {"months": months, "monthly_inflows": revenues, "monthly_outflows": opex}
    except Exception as exc:
        logger.warning("Agent G: ledger fetch failed", error=str(exc))
        return {"months": [], "monthly_inflows": [], "monthly_outflows": []}


# ── LangGraph node ─────────────────────────────────────────────────────────────

def make_g_reporter_node(llm=None):  # llm kept for signature compatibility
    async def g_reporter_node(state: OrchestratorState) -> dict[str, Any]:
        ctx: dict[str, Any] = state["context"]
        mode: str = state.get("mode", "insights")

        # ── 1. Load or fetch monthly cash-flow data ───────────────────────
        raw_ledger: dict[str, Any] = ctx.get("raw_ledger_data") or {}
        if not raw_ledger.get("monthly_inflows"):
            raw_ledger = await _fetch_monthly_cashflows()

        hist_revenue: list[float] = raw_ledger.get("monthly_inflows", [])
        hist_opex: list[float] = raw_ledger.get("monthly_outflows", [])
        months: list[str] = raw_ledger.get("months", [])

        # ── 2. Deterministic 12-month forecast (4 quarters) ───────────────
        fc_revenue = _forecast_series(hist_revenue, periods=12)
        fc_opex = _forecast_series(hist_opex, periods=12)

        # Quarterly aggregates for the narrative prompt
        q_revenue = [round(sum(fc_revenue[i:i+3]), 2) for i in range(0, 12, 3)]
        q_opex = [round(sum(fc_opex[i:i+3]), 2) for i in range(0, 12, 3)]

        # ── 3. Deterministic bankability score ────────────────────────────
        bankability_score, risk_tier = _compute_bankability_score(
            hist_revenue, hist_opex, fc_revenue, fc_opex
        )

        # ── 4. Gemini narrative generation ────────────────────────────────
        # All numbers are pre-computed; Gemini writes the executive text only.
        narrative_data = json.dumps({
            "historical_months": months[-12:] if months else [],
            "historical_monthly_revenue_kes": hist_revenue[-12:],
            "historical_monthly_opex_kes": hist_opex[-12:],
            "forecast_quarterly_revenue_kes": q_revenue,
            "forecast_quarterly_opex_kes": q_opex,
            "bankability_score": bankability_score,
            "risk_tier": risk_tier,
        }, indent=2)

        narrative_prompt = f"""You are a senior credit analyst at a Kenyan commercial bank.

The following financial data has been computed deterministically from the
SME's double-entry ledger.  Do NOT change, override, or re-compute any
of the numbers.  Your sole task is to write the strategic_narrative.

FINANCIAL SUMMARY:
{narrative_data}

Write a strategic_narrative (3-5 sentences) that:
  1. Characterises the current financial health based on the bankability_score and risk_tier.
  2. References the quarterly revenue / opex forecast trend (Q1-Q4).
  3. Gives 2 specific, actionable recommendations to improve creditworthiness.
  4. Uses KES (Kenyan Shillings) throughout; no markdown, no headers.
"""

        try:
            client = get_gemini_client()
            resp = await client.aio.models.generate_content(
                model=settings.GEMINI_MODEL,
                contents=narrative_prompt,
            )
            narrative: str = (resp.text or "").strip()
        except Exception as exc:
            logger.warning("Agent G: Gemini narrative failed", error=str(exc))
            net_trend = "improving" if (fc_revenue[-1] - fc_revenue[0]) > 0 else "declining"
            narrative = (
                f"Bankability score {bankability_score}/100 ({risk_tier} risk tier). "
                f"Forecast revenue trend is {net_trend} over the next 4 quarters. "
                f"Recommend tightening OpEx controls and diversifying revenue streams."
            )

        # ── 5. Assemble output ────────────────────────────────────────────
        output = AgentGOutput(
            bankability_score=bankability_score,
            risk_tier=risk_tier,
            strategic_narrative=narrative,
        )

        updated_ctx = dict(ctx)
        updated_ctx["credit_strategy_result"] = output.model_dump()
        # Attach raw forecast for downstream consumers (hub, UI polling)
        updated_ctx["credit_forecast"] = {
            "quarterly_revenue_kes": q_revenue,
            "quarterly_opex_kes": q_opex,
            "historical_months": months[-12:] if months else [],
        }

        summary_msg = (
            f"[g_reporter] Credit strategy complete — "
            f"score {bankability_score}/100 | tier {risk_tier}"
        )
        logger.info(summary_msg, mode=mode)

        return {
            "messages": [AIMessage(content=summary_msg, name="g_reporter")],
            "context": updated_ctx,
        }

    return g_reporter_node
