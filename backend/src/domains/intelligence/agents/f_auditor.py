"""
Agent F — Tax Auditor.

Pipeline:
  1. Read audit context (tax_regime, period, ledger snapshot) from state.
  2. Fetch fresh ledger totals from PostgreSQL when not pre-loaded.
  3. Run deterministic Kenya tax calculations:
        VAT  (16 %) on revenue above the KES 5 M annual registration threshold.
        Corporate Income Tax (30 %) on net profit (revenue − opex).
        Effective Tax Rate  = (vat_due + cit_due) / gross_revenue × 100.
  4. Call the Tax RAG service to retrieve the top-3 KRA knowledge-base
     sections most relevant to the detected tax_regime.
  5. Send ledger summary + RAG context to Gemini structured output to
     produce compliance_flags and kra_references.
  6. Assemble the final AgentFOutput and write to state["context"]["audit_result"].

Trigger: supervisor routes here when state["next"] == "f_auditor".
"""
from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import AIMessage
from pydantic import BaseModel
from sqlalchemy import text

from src.core.config import settings
from src.core.logging import logger
from src.domains.intelligence.llm_client import get_gemini_client
from src.domains.intelligence.schemas import AgentFOutput, OrchestratorState
from src.domains.intelligence.services.tax_rag_service import get_relevant_tax_rules
from src.infrastructure.database.postgres import AsyncSessionLocal

# ── Kenya tax constants ───────────────────────────────────────────────────────
_VAT_RATE = 0.16
_VAT_THRESHOLD_ANNUAL_KES = 5_000_000.0    # KRA mandatory VAT registration
_CIT_RATE = 0.30                           # Standard corporate income tax rate
_AML_REPORTING_THRESHOLD = 1_000_000.0    # Single-transaction AML flag (KES)


# ── Gemini helper schema (compliance flags only) ──────────────────────────────

class _ComplianceAnalysis(BaseModel):
    """Gemini extracts compliance issues from the supplied ledger + KRA context."""
    compliance_flags: list[str]
    kra_references: list[str]
    audit_summary: str


# ── Database helper ───────────────────────────────────────────────────────────

async def _fetch_ledger_totals(period_days: int = 365) -> dict[str, float]:
    """
    Aggregate revenue (credits) and opex (debits) from ledger_entries for the
    given rolling period.  Returns zeros when the table is empty or unavailable.
    """
    sql = text(f"""
        SELECT
            COALESCE(SUM(CASE WHEN transaction_type = 'credit' THEN amount ELSE 0 END), 0) AS revenue,
            COALESCE(SUM(CASE WHEN transaction_type = 'debit'  THEN amount ELSE 0 END), 0) AS opex,
            COUNT(*) AS tx_count,
            MAX(amount) AS max_single_tx
        FROM ledger_entries
        WHERE created_at >= NOW() - INTERVAL '{period_days} days'
    """)
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(sql)
            row = result.fetchone()
        if row:
            return {
                "revenue":      float(row[0] or 0),
                "opex":         float(row[1] or 0),
                "tx_count":     int(row[2] or 0),
                "max_single_tx": float(row[3] or 0),
            }
    except Exception as exc:
        logger.warning("Agent F: ledger fetch failed", error=str(exc))
    return {"revenue": 0.0, "opex": 0.0, "tx_count": 0, "max_single_tx": 0.0}


# ── Deterministic tax calculation ─────────────────────────────────────────────

def _calculate_tax_liability(
    revenue: float,
    opex: float,
    tax_regime: str,
    period_days: int,
) -> tuple[str, float, float]:
    """
    Return (tax_type, tax_liability_kes, effective_tax_rate_pct).

    Annual scaling: multiplies period figures up to a 365-day year so
    the VAT threshold comparison is always on an annualised basis.
    """
    annualisation_factor = 365.0 / max(period_days, 1)
    annual_revenue = revenue * annualisation_factor

    regime_upper = tax_regime.upper()

    if regime_upper == "VAT":
        if annual_revenue >= _VAT_THRESHOLD_ANNUAL_KES:
            vat_liability = revenue * _VAT_RATE
        else:
            vat_liability = 0.0
        etr = (vat_liability / max(revenue, 1.0)) * 100.0
        return "VAT", round(vat_liability, 2), round(etr, 4)

    if regime_upper in ("CORPORATE_TAX", "CIT"):
        net_profit = max(revenue - opex, 0.0)
        cit = net_profit * _CIT_RATE
        etr = (cit / max(revenue, 1.0)) * 100.0
        return "CORPORATE_TAX", round(cit, 2), round(etr, 4)

    # Fallback: combined VAT + CIT (comprehensive audit)
    annual_revenue_for_vat = annual_revenue
    vat = revenue * _VAT_RATE if annual_revenue_for_vat >= _VAT_THRESHOLD_ANNUAL_KES else 0.0
    net_profit = max(revenue - opex, 0.0)
    cit = net_profit * _CIT_RATE
    total_tax = vat + cit
    etr = (total_tax / max(revenue, 1.0)) * 100.0
    return "COMPREHENSIVE", round(total_tax, 2), round(etr, 4)


# ── LangGraph node ─────────────────────────────────────────────────────────────

def make_f_auditor_node(llm=None):  # llm kept for signature compatibility
    async def f_auditor_node(state: OrchestratorState) -> dict:
        ctx: dict[str, Any] = state["context"]
        tax_regime: str = ctx.get("tax_regime", "COMPREHENSIVE")
        period_days: int = int(ctx.get("audit_period_days", 365))
        mode: str = state.get("mode", "insights")

        # ── 1. Ledger totals ─────────────────────────────────────────────
        snapshot: dict[str, float] = ctx.get("ledger_snapshot") or {}
        if not snapshot.get("revenue") and not snapshot.get("total_revenue"):
            snapshot = await _fetch_ledger_totals(period_days)

        revenue: float = float(
            snapshot.get("revenue") or snapshot.get("total_revenue") or 0.0
        )
        opex: float = float(
            snapshot.get("opex") or snapshot.get("total_opex") or 0.0
        )
        max_single_tx: float = float(snapshot.get("max_single_tx", 0.0))
        tx_count: int = int(snapshot.get("tx_count", 0))

        # ── 2. Deterministic tax calculation ─────────────────────────────
        tax_type, tax_liability, etr = _calculate_tax_liability(
            revenue, opex, tax_regime, period_days
        )

        # ── 3. RAG — retrieve relevant KRA sections ───────────────────────
        rag_query = (
            f"Kenya {tax_regime} compliance requirements for SME with "
            f"annual revenue KES {revenue:,.0f}"
        )
        kra_excerpts: list[str] = await get_relevant_tax_rules(rag_query, limit=3)
        rag_context_text = (
            "\n\n---\n\n".join(kra_excerpts)
            if kra_excerpts
            else "No KRA excerpts available; apply general compliance rules."
        )

        # ── 4. Gemini compliance analysis ─────────────────────────────────
        ledger_summary = json.dumps({
            "tax_regime": tax_regime,
            "period_days": period_days,
            "gross_revenue_kes": revenue,
            "total_opex_kes": opex,
            "net_profit_kes": round(revenue - opex, 2),
            "tax_type": tax_type,
            "tax_liability_kes": tax_liability,
            "effective_tax_rate_pct": etr,
            "transaction_count": tx_count,
            "max_single_transaction_kes": max_single_tx,
            "aml_flag": max_single_tx >= _AML_REPORTING_THRESHOLD,
        }, indent=2)

        compliance_prompt = f"""You are a Kenyan tax compliance auditor.

LEDGER SUMMARY:
{ledger_summary}

RELEVANT KRA KNOWLEDGE BASE EXCERPTS:
{rag_context_text}

Using only the data above:
1. List all compliance issues (compliance_flags). Include:
   - AML flag if max_single_transaction_kes >= {_AML_REPORTING_THRESHOLD:,.0f}
   - VAT registration gap if revenue near or above the threshold
   - Any missing documentation implied by the data
2. List the exact KRA document sections referenced (kra_references), drawn
   only from the excerpts above.
3. Write a concise audit_summary (2-3 sentences).

Return your analysis as a JSON object with fields:
  compliance_flags (array of strings)
  kra_references   (array of strings)
  audit_summary    (string)
"""

        try:
            client = get_gemini_client()
            from google.genai import types as genai_types
            resp = await client.aio.models.generate_content(
                model=settings.GEMINI_MODEL,
                contents=compliance_prompt,
                config=genai_types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=_ComplianceAnalysis,
                ),
            )
            analysis = _ComplianceAnalysis.model_validate_json(resp.text)
        except Exception as exc:
            logger.warning("Agent F: Gemini compliance analysis failed", error=str(exc))
            aml_flag = max_single_tx >= _AML_REPORTING_THRESHOLD
            analysis = _ComplianceAnalysis(
                compliance_flags=(
                    ["Large transaction exceeds AML reporting threshold"]
                    if aml_flag else []
                ),
                kra_references=[e[:120] for e in kra_excerpts[:2]],
                audit_summary=(
                    f"Automated {tax_type} audit for period of {period_days} days. "
                    f"Estimated liability: KES {tax_liability:,.2f}."
                ),
            )

        # ── 5. Assemble output ────────────────────────────────────────────
        output = AgentFOutput(
            tax_type=tax_type,
            tax_liability=tax_liability,
            effective_tax_rate=etr,
            compliance_flags=analysis.compliance_flags,
            kra_references=analysis.kra_references,
            audit_summary=analysis.audit_summary,
        )

        updated_ctx = dict(ctx)
        updated_ctx["audit_result"] = output.model_dump()

        summary_msg = (
            f"[f_auditor] {tax_type} audit complete — "
            f"liability KES {tax_liability:,.2f} | ETR {etr:.1f}% | "
            f"{len(analysis.compliance_flags)} compliance flag(s) | "
            f"{len(analysis.kra_references)} KRA reference(s)"
        )
        logger.info(summary_msg, mode=mode)

        return {
            "messages": [AIMessage(content=summary_msg, name="f_auditor")],
            "context": updated_ctx,
        }

    return f_auditor_node
