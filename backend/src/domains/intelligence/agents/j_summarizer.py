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
import re
from typing import Any

from langchain_core.messages import AIMessage

from src.core.logging import logger
from src.domains.intelligence.agent_registry import executive_summary_keys
from src.domains.intelligence.llm_client import generate_structured_content
from src.domains.intelligence.schemas import (
    ExecutiveSummary,
    OrchestratorState,
    SummaryBullet,
)

# Numeric tokens (KES figures, percentages, scores) that MUST survive a
# translation unchanged — used by the fidelity check below.
_NUMBER_RE = re.compile(r"\d[\d,\.]*")


def _numeric_tokens(text: str) -> set[str]:
    return {t.rstrip(".,") for t in _NUMBER_RE.findall(text)}


def _render_bullets(bullets: list[SummaryBullet]) -> str:
    """Deterministically render structured bullets to the legacy markdown string."""
    return "\n".join(f"• **{b.label}:** {b.text}" for b in bullets)


def _translation_preserves_numbers(source: list[SummaryBullet], dest: list[SummaryBullet]) -> bool:
    """True when every numeric token in the source bullets appears in the translation."""
    src_numbers = set().union(*(_numeric_tokens(b.text) for b in source)) if source else set()
    dst_numbers = set().union(*(_numeric_tokens(b.text) for b in dest)) if dest else set()
    return src_numbers <= dst_numbers

# The agent output keys inspected for the summary (in logical report order) are
# sourced from the single agent registry at call time — see ``_collect_sections``
# — so a new agent needs no edit here.

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
    "hub_artifact_ids",          # hub_writer bookkeeping, not an agent finding
    "hub_genui_artifact_ids",    # hub_writer bookkeeping, not an agent finding
    "executive_summary_bullets",  # J's own structured output
})


def _collect_sections(ctx: dict[str, Any]) -> dict[str, Any]:
    """Return the non-empty agent output sub-dict from context."""
    sections: dict[str, Any] = {}
    for key in executive_summary_keys():
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

        prompt = f"""\
You are a financial briefing specialist preparing a C-suite executive summary for a Kenyan SME.

## Agent Intelligence Outputs
{context_payload}

## Task
Distil ALL findings above into EXACTLY 3-5 executive bullets. Return JSON with a
"bullets" array; each element is {{label, text}} where label is one of
"Budget Health", "Cash Flow", "Credit Risk", "Tax Compliance", "Advisory".
Reference specific KES figures, scores, or flags from the data. Plain language,
no markdown inside text.
"""

        # ── 3. Structured generation (no fragile string parsing) ───────────
        try:
            result = await generate_structured_content(prompt, ExecutiveSummary)
            bullets = result.bullets[:5]
        except Exception as exc:
            logger.warning("Agent J: Gemini summarisation failed", error=str(exc))
            bullets = _fallback_bullets(sections)

        if not bullets:
            bullets = [
                SummaryBullet(label="Summary", text="Analysis complete — review agent outputs.")
            ]

        # ── 4. Locale translation with a numeric-fidelity guard ────────────
        localised = preferred_locale.lower() not in ("en", "english", "")
        if localised:
            translated = await _translate_bullets(bullets, preferred_locale)
            if translated and _translation_preserves_numbers(bullets, translated):
                bullets = translated
            else:
                logger.warning(
                    "Agent J: translation dropped/altered numeric figures — keeping source",
                    locale=preferred_locale,
                )
                localised = False

        summary_text = _render_bullets(bullets)

        summary_msg = f"[j_summarizer] {len(bullets)} executive bullet(s) generated"
        if localised:
            summary_msg += f" | locale: {preferred_locale}"
        logger.info(summary_msg, mode=mode)

        return {
            "messages": [AIMessage(content=summary_text, name="j_summarizer")],
            "context": {
                "executive_summary": summary_text,                     # back-compat string
                "executive_summary_bullets": [b.model_dump() for b in bullets],
            },
        }

    return j_summarizer_node


def _fallback_bullets(sections: dict[str, Any]) -> list[SummaryBullet]:
    """Deterministic per-section bullets when the LLM call fails."""
    bullets: list[SummaryBullet] = []

    adv = sections.get("advice") or {}
    if adv:
        outlook = adv.get("overall_outlook", "")
        bullets.append(SummaryBullet(
            label="Advisory",
            text=outlook or "Recommendations generated — see advice section.",
        ))

    cr = sections.get("credit_strategy_result") or {}
    if cr:
        bullets.append(SummaryBullet(
            label="Credit Risk",
            text=f"Bankability score {cr.get('bankability_score', 'N/A')}/100 "
                 f"({cr.get('risk_tier', 'N/A')} tier).",
        ))

    fa = sections.get("audit_result") or {}
    if fa:
        bullets.append(SummaryBullet(
            label="Tax Compliance",
            text=f"{fa.get('tax_type', 'Tax')} liability KES {fa.get('tax_liability', 0):,.0f} | "
                 f"{len(fa.get('compliance_flags', []))} compliance flag(s).",
        ))

    wd = sections.get("watchdog_analysis") or {}
    if wd:
        bullets.append(SummaryBullet(
            label="Budget Health",
            text=f"{wd.get('current_state', 'UNKNOWN')} state | "
                 f"anomaly score {wd.get('anomaly_score', 0):.2f}.",
        ))

    return bullets[:5]


async def _translate_bullets(
    bullets: list[SummaryBullet], locale: str
) -> list[SummaryBullet] | None:
    """Translate bullet text into ``locale``, preserving numerals. None on failure."""
    payload = json.dumps([b.model_dump() for b in bullets])
    prompt = (
        f"Translate the 'text' of each bullet into '{locale}'. Keep the 'label' "
        "values in English and preserve EVERY monetary figure, percentage, and "
        "score exactly as numerals. Return the same JSON shape.\n\n"
        f"{payload}"
    )
    try:
        result = await generate_structured_content(prompt, ExecutiveSummary)
        return result.bullets
    except Exception as exc:
        logger.warning("Agent J: translation call failed", error=str(exc))
        return None
