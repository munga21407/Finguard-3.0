"""
Agent J — Executive Summarizer.

Pipeline:
  1. Enumerate populated agent-output keys in state["context"].
  2. Pass only non-empty sections to Gemini (avoids token waste on empty stubs).
  3. Gemini Flash produces exactly 3-5 bullet-point executive summary.
  4. If CRM profile specifies a preferred locale (e.g., Swahili, Sheng), the
     model translates the bullets into that locale while preserving KES figures.
  5. Write plain text to context["executive_summary"].

Cost note: Gemini 2.5 Flash is used directly (default model). Summarisation
requires less reasoning depth than forecasting or advisory; Flash is the
cost-efficient choice already in this stack vs. Pro variants.
"""
from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import AIMessage

from src.core.config import settings
from src.core.logging import logger
from src.domains.intelligence.llm_client import get_gemini_client
from src.domains.intelligence.schemas import OrchestratorState

# Agent output keys inspected for the summary, in logical report order.
_AGENT_OUTPUT_KEYS = (
    "advice",
    "audit_result",
    "credit_strategy_result",
    "watchdog_analysis",
    "forecast",
    "reconciliation_report",
    "classified_transactions",
    "extracted_invoice",
    "external_data",
)

# Operational / scaffolding keys excluded from the summary payload.
_SKIP_KEYS = frozenset({
    "executive_summary",         # avoid circularity
    "raw_ledger_data",
    "document_text",
    "candidate_invoice",
    "hub_artifact_id",
    "audit_trail",
    "current_intent",
    "account_id",
    "watchdog_period_days",
    "tax_regime",
    "audit_period_days",
    "ledger_snapshot",
    "crm_profile",
    "user_role",
    "customer_id",
    "credit_forecast",
    "budget_watchdog_result",    # duplicate of watchdog_analysis
    "credit_report_pdf_b64",
    "credit_forecast_xlsx_b64",
})


def _collect_sections(ctx: dict[str, Any]) -> dict[str, Any]:
    """Return the non-empty agent output sub-dict from context."""
    sections: dict[str, Any] = {}
    for key in _AGENT_OUTPUT_KEYS:
        val = ctx.get(key)
        if val and val != {} and val != []:
            sections[key] = val
    # Include any additional agent output keys not in the standard list
    for key, val in ctx.items():
        if (
            key not in sections
            and key not in _SKIP_KEYS
            and isinstance(val, (dict, list))
            and val
        ):
            sections[key] = val
    return sections


def make_j_summarizer_node(llm: Any = None) -> Any:  # llm kept for signature compatibility
    async def j_summarizer_node(state: OrchestratorState) -> dict[str, Any]:
        ctx: dict[str, Any] = state["context"]
        mode: str = state.get("mode", "insights")

        # ── 1. Collect populated agent outputs ───────────────────────────
        sections = _collect_sections(ctx)
        crm_profile: dict[str, Any] = ctx.get("crm_profile") or {}
        preferred_locale: str = str(
            crm_profile.get("preferred_locale")
            or ctx.get("preferred_locale")
            or "en"
        )

        # ── 2. Build distillation payload ─────────────────────────────────
        context_payload = json.dumps(sections, indent=2, default=str)

        # ── 3. Locale translation instruction ─────────────────────────────
        locale_note = ""
        if preferred_locale.lower() not in ("en", "english", ""):
            locale_note = (
                f"\n\nIMPORTANT: Translate the final bullet points into '{preferred_locale}'. "
                "Preserve all KES monetary figures, percentages, and scores as numerals."
            )

        prompt = f"""\
You are a financial briefing specialist preparing a C-suite executive summary for a Kenyan SME.

## Agent Intelligence Outputs
{context_payload}

## Task
Distil ALL findings above into EXACTLY 3-5 executive bullet points.

Rules:
- Start every bullet with "•"
- Each bullet begins with a bold label:
  **Budget Health:**, **Cash Flow:**, **Credit Risk:**, **Tax Compliance:**, or **Advisory:**
- Reference specific KES figures, scores, or flags from the data where available
- Plain language only — no jargon, no sub-bullets, no markdown beyond bold labels
- Output bullet points ONLY — no preamble, no headings, no closing remarks{locale_note}
"""

        try:
            client = get_gemini_client()
            resp = await client.aio.models.generate_content(
                model=settings.GEMINI_MODEL,
                contents=prompt,
            )
            summary_text: str = (resp.text or "").strip()
        except Exception as exc:
            logger.warning("Agent J: Gemini summarisation failed", error=str(exc))
            lines: list[str] = []

            adv = sections.get("advice") or {}
            if adv:
                outlook = adv.get("overall_outlook", "")
                lines.append(
                    f"• **Advisory:** {outlook}"
                    if outlook
                    else "• **Advisory:** Recommendations generated — see advice section."
                )

            cr = sections.get("credit_strategy_result") or {}
            if cr:
                lines.append(
                    f"• **Credit Risk:** Bankability score "
                    f"{cr.get('bankability_score', 'N/A')}/100 "
                    f"({cr.get('risk_tier', 'N/A')} tier)."
                )

            fa = sections.get("audit_result") or {}
            if fa:
                lines.append(
                    f"• **Tax Compliance:** {fa.get('tax_type', 'Tax')} liability "
                    f"KES {fa.get('tax_liability', 0):,.0f} | "
                    f"{len(fa.get('compliance_flags', []))} compliance flag(s)."
                )

            wd = sections.get("watchdog_analysis") or {}
            if wd:
                lines.append(
                    f"• **Budget Health:** {wd.get('current_state', 'UNKNOWN')} state | "
                    f"anomaly score {wd.get('anomaly_score', 0):.2f}."
                )

            if not lines:
                lines.append("• **Summary:** Analysis complete — review individual agent outputs.")

            summary_text = "\n".join(lines[:5])

        updated_ctx = dict(ctx)
        updated_ctx["executive_summary"] = summary_text

        bullet_count = summary_text.count("•")
        summary_msg = f"[j_summarizer] {bullet_count} executive bullet(s) generated"
        if preferred_locale.lower() not in ("en", "english", ""):
            summary_msg += f" | locale: {preferred_locale}"
        logger.info(summary_msg, mode=mode)

        return {
            "messages": [AIMessage(content=summary_text, name="j_summarizer")],
            "context": updated_ctx,
        }

    return j_summarizer_node
