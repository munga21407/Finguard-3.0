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
from datetime import date
from typing import Any

from langchain_core.messages import AIMessage
from pydantic import BaseModel
from sqlalchemy import text

from src.core.logging import logger
from src.domains.intelligence.db_tuning import (
    get_effective_auditor_tuning,
    refresh_agent_tuning_from_db,
)
from src.domains.intelligence.llm_client import generate_structured_content
from src.domains.intelligence.schemas import (
    AgentFOutput,
    CompositeGenUIPayload,
    KeyFinding,
    OrchestratorState,
)
from src.domains.intelligence.services.tax_rag_service import get_relevant_tax_rules
from src.domains.intelligence.tuning import AuditorTuning
from src.infrastructure.database.postgres import AsyncSessionLocal

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
            COALESCE(SUM(CASE WHEN transaction_type = 'credit'
                             THEN amount ELSE 0 END), 0) AS revenue,
            COALESCE(SUM(CASE WHEN transaction_type = 'debit'
                             THEN amount ELSE 0 END), 0) AS opex,
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
    rates: AuditorTuning,
) -> tuple[str, float, float]:
    """
    Return (tax_type, tax_liability_kes, effective_tax_rate_pct).

    ``rates`` carries the period-correct VAT/CIT rates + threshold (see
    ``db_tuning.get_effective_auditor_tuning``).  Annual scaling: multiplies
    period figures up to a 365-day year so the VAT threshold comparison is
    always on an annualised basis.
    """
    annualisation_factor = 365.0 / max(period_days, 1)
    annual_revenue = revenue * annualisation_factor
    threshold = rates.vat_threshold_annual_kes

    regime_upper = tax_regime.upper()

    if regime_upper == "VAT":
        vat_liability = revenue * rates.vat_rate if annual_revenue >= threshold else 0.0
        etr = (vat_liability / max(revenue, 1.0)) * 100.0
        return "VAT", round(vat_liability, 2), round(etr, 4)

    if regime_upper in ("CORPORATE_TAX", "CIT"):
        net_profit = max(revenue - opex, 0.0)
        cit = net_profit * rates.cit_rate
        etr = (cit / max(revenue, 1.0)) * 100.0
        return "CORPORATE_TAX", round(cit, 2), round(etr, 4)

    # Fallback: combined VAT + CIT (comprehensive audit)
    vat = revenue * rates.vat_rate if annual_revenue >= threshold else 0.0
    net_profit = max(revenue - opex, 0.0)
    cit = net_profit * rates.cit_rate
    total_tax = vat + cit
    etr = (total_tax / max(revenue, 1.0)) * 100.0
    return "COMPREHENSIVE", round(total_tax, 2), round(etr, 4)


# ── Deterministic compliance-flag guards (machine-verified, not LLM-decided) ──

def _inject_deterministic_flags(
    flags: list[str],
    *,
    max_single_tx: float,
    aml_threshold: float,
    annual_revenue: float,
    vat_threshold: float,
    tax_type: str,
) -> list[str]:
    """Return ``flags`` with the machine-verified compliance flags guaranteed present.

    Gemini may or may not surface these in its free-text output; we enforce them
    from the deterministic figures so they can never be silently absent — the LLM
    verdict is never the only gate:
      * AML_REPORTING_REQUIRED  — a single transaction ≥ the AML threshold.
      * VAT_REGISTRATION_REQUIRED — annualised revenue ≥ the VAT threshold but VAT
        was not assessed (tax_type is neither VAT nor COMPREHENSIVE).
    """
    out = list(flags)
    if max_single_tx >= aml_threshold and not any("AML_REPORTING_REQUIRED" in f for f in out):
        out.append("AML_REPORTING_REQUIRED")
    if (
        annual_revenue >= vat_threshold
        and tax_type not in ("VAT", "COMPREHENSIVE")
        and not any("VAT_REGISTRATION_REQUIRED" in f for f in out)
    ):
        out.append("VAT_REGISTRATION_REQUIRED")
    return out


# ── LangGraph node ─────────────────────────────────────────────────────────────

def make_f_auditor_node(llm: Any = None) -> Any:  # llm kept for signature compatibility
    async def f_auditor_node(state: OrchestratorState) -> dict[str, Any]:
        ctx: dict[str, Any] = state["context"]
        tax_regime: str = ctx.get("tax_regime", "COMPREHENSIVE")
        period_days: int = int(ctx.get("audit_period_days", 365))
        mode: str = state.get("mode", "insights")

        # ── 0. Period-correct tax rates (effective-dated) ─────────────────
        # Refresh any runtime tuning overrides, then resolve the VAT/CIT rates
        # + thresholds that were in force at the audit date (ctx["as_of_date"],
        # default today) so a historical re-audit uses period-correct rates.
        as_of: date | None = None
        raw_as_of = ctx.get("as_of_date")
        if raw_as_of:
            try:
                as_of = date.fromisoformat(str(raw_as_of))
            except ValueError:
                logger.warning("Agent F: invalid as_of_date; using today", value=raw_as_of)
        await refresh_agent_tuning_from_db()
        async with AsyncSessionLocal() as session:
            eff = await get_effective_auditor_tuning(session, as_of)
        vat_threshold = eff.vat_threshold_annual_kes
        aml_threshold = eff.aml_reporting_threshold_kes

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
            revenue, opex, tax_regime, period_days, eff
        )
        _annual_rev = revenue * (365.0 / max(period_days, 1))
        vat_component = (
            round(revenue * eff.vat_rate, 2) if _annual_rev >= vat_threshold else 0.0
        )
        cit_component = round(max(revenue - opex, 0.0) * eff.cit_rate, 2)
        if tax_regime.upper() == "VAT":
            vat_component, cit_component = tax_liability, 0.0
        elif tax_regime.upper() in ("CORPORATE_TAX", "CIT"):
            vat_component, cit_component = 0.0, tax_liability

        # ── 3. RAG — retrieve relevant KRA sections ───────────────────────
        rag_query = (
            f"Kenya {tax_regime} compliance requirements for SME with "
            f"annual revenue KES {revenue:,.0f} — VAT registration, CIT calculation, "
            f"filing deadlines, AML obligations"
        )
        kra_excerpts: list[str] = await get_relevant_tax_rules(rag_query, limit=3)
        rag_context_text = (
            "\n\n---\n\n".join(kra_excerpts)
            if kra_excerpts
            else "No KRA excerpts available; apply general Kenya tax compliance rules."
        )

        # Extract citation labels from the formatted excerpts ("KRA Ref: X — Y")
        # so Gemini can echo them back precisely in kra_references
        rag_citations = [
            line.strip("[]")
            for exc in kra_excerpts
            for line in exc.split("\n")[:1]
            if line.startswith("[KRA Ref:")
        ]

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
            "aml_flag": max_single_tx >= aml_threshold,
        }, indent=2)

        compliance_prompt = f"""You are a Kenya Revenue Authority (KRA) tax compliance auditor
for an SME financial operations platform.

## Kenya Tax Rate Reference (AUTHORITATIVE — do not override)
- VAT standard rate: {eff.vat_rate:.0%} on taxable supplies
- VAT registration threshold: KES {vat_threshold:,.0f} annual turnover
- Corporate Income Tax (CIT): {eff.cit_rate:.0%} on net profit for resident companies
- Small Business Turnover Tax (TOT): {eff.tot_rate:.0%} of gross turnover (KES 1M–50M band)
- AML single-transaction reporting threshold: KES {aml_threshold:,.0f}

## Ledger Summary (computed by the tax calculation engine)
{ledger_summary}

## Relevant KRA Knowledge Base Excerpts
(Citations are formatted as [KRA Ref: <document> — <section>])
{rag_context_text}

## Instructions
Using ONLY the ledger summary and KRA excerpts above:

1. compliance_flags — list every compliance issue present:
   - AML: flag transactions exceeding KES {aml_threshold:,.0f}
   - VAT gap: flag if annual revenue is at or above KES {vat_threshold:,.0f}
     but VAT has not been assessed (tax_type is not VAT or COMPREHENSIVE)
   - Filing risk: flag any deadline or documentation issues implied by the data
   - Over/under-declaration risks based on the ledger snapshot

2. kra_references — cite the exact "[KRA Ref: …]" labels from the excerpts above.
   If no excerpts are available, use general section references (e.g. "VAT Act S.2",
   "Income Tax Act S.7A"). Do NOT invent document titles not present in the excerpts.

3. audit_summary — 2-3 sentences summarising the audit findings, the total tax
   liability (KES {tax_liability:,.2f}), and the most urgent compliance action.

Return a JSON object with exactly these fields:
  compliance_flags  (array of strings)
  kra_references    (array of strings)
  audit_summary     (string)
"""

        try:
            analysis = await generate_structured_content(compliance_prompt, _ComplianceAnalysis)
        except Exception as exc:
            logger.warning("Agent F: Gemini compliance analysis failed", error=str(exc))
            aml_flag = max_single_tx >= aml_threshold
            fallback_flags = []
            if aml_flag:
                fallback_flags.append(
                    f"Large transaction KES {max_single_tx:,.0f} exceeds AML "
                    f"reporting threshold of KES {aml_threshold:,.0f}"
                )
            analysis = _ComplianceAnalysis(
                compliance_flags=fallback_flags,
                kra_references=(
                    rag_citations[:3]
                    if rag_citations
                    else ["Kenya VAT Act S.2", "Income Tax Act S.7"]
                ),
                audit_summary=(
                    f"Automated {tax_type} audit for {period_days}-day period. "
                    f"Estimated tax liability: KES {tax_liability:,.2f} "
                    f"(ETR {etr:.1f}%). "
                    f"Review KRA excerpts for detailed compliance guidance."
                ),
            )

        # ── 5. Deterministic compliance-flag guards (machine-verified) ─────
        before = set(analysis.compliance_flags)
        analysis.compliance_flags = _inject_deterministic_flags(
            analysis.compliance_flags,
            max_single_tx=max_single_tx,
            aml_threshold=aml_threshold,
            annual_revenue=_annual_rev,
            vat_threshold=vat_threshold,
            tax_type=tax_type,
        )
        injected = [f for f in analysis.compliance_flags if f not in before]
        if injected:
            logger.info("Agent F: deterministic compliance flags injected", flags=injected)

        # ── 6. Assemble output ────────────────────────────────────────────
        output = AgentFOutput(
            tax_type=tax_type,
            tax_liability=tax_liability,
            effective_tax_rate=etr,
            compliance_flags=analysis.compliance_flags,
            kra_references=analysis.kra_references,
            audit_summary=analysis.audit_summary,
        )

        audit_dump = output.model_dump()

        summary_msg = (
            f"[f_auditor] {tax_type} audit complete — "
            f"liability KES {tax_liability:,.2f} | ETR {etr:.1f}% | "
            f"{len(analysis.compliance_flags)} compliance flag(s) | "
            f"{len(analysis.kra_references)} KRA reference(s)"
        )
        logger.info(summary_msg, mode=mode)

        # ── 7. Emit CompositeGenUIPayload ─────────────────────────────────
        findings: list[KeyFinding] = [
            KeyFinding(metric="Tax Type", value=tax_type),
            KeyFinding(metric="Liability", value=f"KES {tax_liability:,.2f}"),
            KeyFinding(metric="ETR", value=f"{etr:.1f}%"),
            KeyFinding(metric="Flags", value=f"{len(analysis.compliance_flags)} issue(s)"),
        ]
        composite = CompositeGenUIPayload(
            component_id="TaxLiabilityDonut",
            props={
                **output.model_dump(),
                "vat_component": vat_component,
                "cit_component": cit_component,
            },
            findings=findings,
            fallback_text=(
                f"Tax audit: {tax_type} | liability KES {tax_liability:,.2f} | "
                f"ETR {etr:.1f}% | {len(analysis.compliance_flags)} compliance flag(s)."
            ),
        )

        return {
            "messages": [AIMessage(content=summary_msg, name="f_auditor")],
            "context": {"audit_result": audit_dump},
            "gen_ui_payloads": [composite.to_gen_ui_payload()],
        }

    return f_auditor_node
