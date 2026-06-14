"""
LLM-as-judge eval for Agent F's *narrative* (scaffold).

The deterministic numbers are gated by `test_agent_f_tax_evals.py`. This file
covers the part a unit test can't: whether the LLM-written `audit_summary` is
**numerically grounded** — i.e. it states a tax liability consistent with the
figure the calculation engine computed, rather than contradicting it.

This is intentionally separate and **non-blocking**:
  * it costs tokens and needs `GEMINI_API_KEY`, so it is skipped unless
    `RUN_LLM_EVALS=1`;
  * LLM-as-judge is non-deterministic, so it must never gate a PR — it runs
    nightly (see the `llm-evals` job in `.github/workflows/ci.yml`).

Extend this with more scenarios / a citation-grounding judge as needed; treat it
as the template for narrative quality evals, not an exhaustive suite.
"""
from __future__ import annotations

import os

import pytest
from pydantic import BaseModel

from src.domains.intelligence.agents.f_auditor import _calculate_tax_liability
from src.domains.intelligence.llm_client import (
    generate_structured_content,
    generate_text_content,
)
from tests.evals.datasets import TAX_CASES

pytestmark = [
    pytest.mark.llm_judge,
    pytest.mark.skipif(
        not os.getenv("RUN_LLM_EVALS"),
        reason="LLM-judge evals are nightly/opt-in — set RUN_LLM_EVALS=1 (needs GEMINI_API_KEY)",
    ),
]


class _JudgeVerdict(BaseModel):
    grounded: bool
    reason: str


def _narrative_prompt(case: object, liability: float, etr: float) -> str:
    return (
        "Write a 2-3 sentence Kenya tax audit summary for an SME. "
        f"The tax calculation engine computed a total tax liability of "
        f"KES {liability:,.2f} at an effective tax rate of {etr:.2f}%. "
        "State the liability figure accurately; do not invent a different number."
    )


async def _judge_numeric_grounding(summary: str, expected_liability: float) -> _JudgeVerdict:
    prompt = (
        "You are evaluating whether a tax audit summary is numerically grounded.\n"
        f'Expected total tax liability: KES {expected_liability:,.2f}.\n'
        f'Summary under review: "{summary}"\n\n'
        "Return JSON {grounded: bool, reason: string}. Set grounded=true only if the "
        "summary states a tax liability consistent with the expected figure and "
        "contains no contradicting monetary amount."
    )
    return await generate_structured_content(prompt, _JudgeVerdict)


@pytest.mark.asyncio
async def test_agent_f_narrative_is_numerically_grounded() -> None:
    case = next(c for c in TAX_CASES if c.id == "cit_profitable")
    _type, liability, etr = _calculate_tax_liability(
        case.revenue, case.opex, case.tax_regime, case.period_days
    )

    summary = await generate_text_content(_narrative_prompt(case, liability, etr))
    verdict = await _judge_numeric_grounding(summary, liability)

    assert verdict.grounded, f"narrative not grounded in KES {liability:,.2f}: {verdict.reason}"
