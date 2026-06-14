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
  5. Generate a professional PDF report (reportlab) and an Excel workbook
     (pandas/openpyxl) containing the full 12-month forecast; both are
     base64-encoded and stored in context for the hub_writer to persist.
  6. Assemble AgentGOutput and write to state["context"]["credit_strategy_result"].

Trigger: supervisor routes here when state["next"] == "g_reporter".
"""
from __future__ import annotations

import base64
import json
from datetime import UTC, datetime
from io import BytesIO
from typing import Any

import numpy as np
from langchain_core.messages import AIMessage
from sqlalchemy import text

from src.core.config import settings
from src.core.logging import logger
from src.domains.intelligence.llm_client import get_gemini_client
from src.domains.intelligence.schemas import (
    AgentGOutput,
    CompositeGenUIPayload,
    KeyFinding,
    OrchestratorState,
)
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
) -> tuple[int, str, dict[str, int]]:
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
    sub_scores: dict[str, int] = {
        "trend_score": trend_score,
        "ratio_score": ratio_score,
        "consistency_score": consistency_score,
        "runway_score": runway_score,
    }
    return total, tier, sub_scores


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


# ── Export helpers ────────────────────────────────────────────────────────────

def _generate_pdf_report(
    bankability_score: int,
    risk_tier: str,
    narrative: str,
    q_revenue: list[float],
    q_opex: list[float],
) -> bytes:
    """Generate a professional credit strategy PDF using reportlab."""
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import cm
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

        tier_color_map = {
            "LOW":    colors.HexColor("#16a34a"),
            "MEDIUM": colors.HexColor("#d97706"),
            "HIGH":   colors.HexColor("#dc2626"),
        }
        tier_color = tier_color_map.get(risk_tier.upper(), colors.black)

        buffer = BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            topMargin=2 * cm,
            bottomMargin=2 * cm,
            leftMargin=2 * cm,
            rightMargin=2 * cm,
        )
        styles = getSampleStyleSheet()

        title_style = ParagraphStyle(
            "FinguardTitle",
            parent=styles["Title"],
            fontSize=18,
            spaceAfter=8,
        )
        score_style = ParagraphStyle(
            "BankabilityScore",
            parent=styles["Normal"],
            fontSize=52,
            textColor=tier_color,
            alignment=1,   # CENTER
            spaceAfter=2,
        )
        tier_style = ParagraphStyle(
            "RiskTier",
            parent=styles["Normal"],
            fontSize=16,
            textColor=tier_color,
            alignment=1,
            spaceAfter=16,
        )
        label_style = ParagraphStyle(
            "ScoreLabel",
            parent=styles["Normal"],
            fontSize=10,
            textColor=colors.HexColor("#6b7280"),
            alignment=1,
            spaceAfter=0,
        )

        generated_at = datetime.now(UTC).strftime("%d %B %Y")

        story = [
            Paragraph("Finguard 3.0 — Credit Strategy Report", title_style),
            Paragraph(f"Generated: {generated_at}", styles["Normal"]),
            Spacer(1, 0.4 * cm),
            Paragraph("BANKABILITY SCORE", label_style),
            Paragraph(str(bankability_score), score_style),
            Paragraph(f"{risk_tier} RISK TIER", tier_style),
            Paragraph("Strategic Narrative", styles["Heading2"]),
            Paragraph(narrative, styles["Normal"]),
            Spacer(1, 0.5 * cm),
        ]

        if q_revenue and q_opex:
            story.append(Paragraph("4-Quarter Cash Flow Forecast (KES)", styles["Heading2"]))
            header_bg = colors.HexColor("#1a1a2e")
            rows = [["Quarter", "Projected Revenue", "Projected OpEx", "Net Cash Flow"]]
            style_cmds: list[tuple[Any, ...]] = [
                ("BACKGROUND",  (0, 0), (-1, 0), header_bg),
                ("TEXTCOLOR",   (0, 0), (-1, 0), colors.white),
                ("FONTNAME",    (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE",    (0, 0), (-1, -1), 9),
                ("GRID",        (0, 0), (-1, -1), 0.5, colors.HexColor("#e5e7eb")),
                ("ALIGN",       (1, 0), (-1, -1), "RIGHT"),
                ("TOPPADDING",  (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
            for i, (rev, opx) in enumerate(zip(q_revenue, q_opex, strict=False)):
                net = round(rev - opx, 2)
                rows.append([
                    f"Q{i + 1}",
                    f"KES {rev:,.0f}",
                    f"KES {opx:,.0f}",
                    f"KES {net:,.0f}",
                ])
                if i % 2 == 0:
                    style_cmds.append(
                        ("BACKGROUND", (0, i + 1), (-1, i + 1), colors.HexColor("#f9fafb"))
                    )

            table = Table(rows, colWidths=[3 * cm, 4.5 * cm, 4.5 * cm, 4.5 * cm])
            table.setStyle(TableStyle(style_cmds))
            story.append(table)

        story += [
            Spacer(1, 0.5 * cm),
            Paragraph(
                "All numerical figures are deterministically computed from "
                "double-entry ledger data. "
                "This report was generated automatically by Finguard 3.0 AI agents.",
                styles["Italic"],
            ),
        ]

        doc.build(story)
        return buffer.getvalue()

    except Exception as exc:
        logger.warning("Agent G: PDF generation failed", error=str(exc))
        return b""


def _generate_forecast_excel(
    fc_revenue: list[float],
    fc_opex: list[float],
    hist_months: list[str],
    hist_revenue: list[float],
    hist_opex: list[float],
) -> bytes:
    """Generate a two-sheet Excel workbook with forecast and historical data."""
    try:
        import pandas as pd

        buffer = BytesIO()
        month_labels = [f"Month +{i + 1}" for i in range(len(fc_revenue))]
        fc_net = [round(r - o, 2) for r, o in zip(fc_revenue, fc_opex, strict=False)]

        forecast_df = pd.DataFrame({
            "Month":                    month_labels,
            "Projected Revenue (KES)":  fc_revenue,
            "Projected OpEx (KES)":     fc_opex,
            "Net Cash Flow (KES)":      fc_net,
        })

        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
            forecast_df.to_excel(writer, sheet_name="12-Month Forecast", index=False)

            if hist_revenue and hist_opex:
                n = min(len(hist_revenue), len(hist_opex))
                hist_labels = (
                    hist_months[:n]
                    if hist_months
                    else [f"Month -{n - i}" for i in range(n)]
                )
                hist_net = [
                    round(r - o, 2)
                    for r, o in zip(hist_revenue[:n], hist_opex[:n], strict=False)
                ]
                hist_df = pd.DataFrame({
                    "Month":            hist_labels,
                    "Revenue (KES)":    hist_revenue[:n],
                    "OpEx (KES)":       hist_opex[:n],
                    "Net Cash Flow (KES)": hist_net,
                })
                hist_df.to_excel(writer, sheet_name="Historical Data", index=False)

        return buffer.getvalue()

    except Exception as exc:
        logger.warning("Agent G: Excel generation failed", error=str(exc))
        return b""


# ── LangGraph node ─────────────────────────────────────────────────────────────

def make_g_reporter_node(llm: Any = None) -> Any:  # llm kept for signature compatibility
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
        q_revenue = [round(sum(fc_revenue[i:i + 3]), 2) for i in range(0, 12, 3)]
        q_opex = [round(sum(fc_opex[i:i + 3]), 2) for i in range(0, 12, 3)]

        # ── 3. Deterministic bankability score ────────────────────────────
        bankability_score, risk_tier, sub_scores = _compute_bankability_score(
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

        # ── 5. PDF and Excel export generation ───────────────────────────
        pdf_bytes = _generate_pdf_report(
            bankability_score, risk_tier, narrative, q_revenue, q_opex
        )
        xlsx_bytes = _generate_forecast_excel(
            fc_revenue, fc_opex,
            hist_months=months[-12:] if months else [],
            hist_revenue=hist_revenue[-12:],
            hist_opex=hist_opex[-12:],
        )

        # ── 6. Assemble output ────────────────────────────────────────────
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
        # Base64-encoded exports for hub_writer to persist in MongoDB
        if pdf_bytes:
            updated_ctx["credit_report_pdf_b64"] = base64.b64encode(pdf_bytes).decode("ascii")
        if xlsx_bytes:
            updated_ctx["credit_forecast_xlsx_b64"] = base64.b64encode(xlsx_bytes).decode("ascii")

        summary_msg = (
            f"[g_reporter] Credit strategy complete — "
            f"score {bankability_score}/100 | tier {risk_tier} | "
            f"pdf={'yes' if pdf_bytes else 'no'} "
            f"xlsx={'yes' if xlsx_bytes else 'no'}"
        )
        logger.info(summary_msg, mode=mode)

        # ── Emit CompositeGenUIPayload ─────────────────────────────────────
        findings: list[KeyFinding] = [
            KeyFinding(metric="Score", value=f"{bankability_score}/100"),
            KeyFinding(metric="Risk Tier", value=risk_tier),
            KeyFinding(
                metric="Q1 Revenue",
                value=f"KES {q_revenue[0]:,.0f}" if q_revenue else "N/A",
            ),
            KeyFinding(metric="Q1 OpEx", value=f"KES {q_opex[0]:,.0f}" if q_opex else "N/A"),
        ]
        composite = CompositeGenUIPayload(
            component_id="BankabilityScoreRadar",
            props={
                "bankability_score": bankability_score,
                "risk_tier": risk_tier,
                "strategic_narrative": narrative,
                "quarterly_revenue_kes": q_revenue,
                "quarterly_opex_kes": q_opex,
                "historical_months": months[-12:] if months else [],
                **sub_scores,
            },
            findings=findings,
            fallback_text=(
                f"Credit strategy: bankability {bankability_score}/100 ({risk_tier} risk). "
                f"Q1 projected revenue KES {q_revenue[0]:,.0f}."
                if q_revenue else
                f"Credit strategy: bankability {bankability_score}/100 ({risk_tier} risk)."
            ),
        )

        return {
            "messages": [AIMessage(content=summary_msg, name="g_reporter")],
            "context": updated_ctx,
            "gen_ui_payloads": [composite.to_gen_ui_payload()],
        }

    return g_reporter_node
