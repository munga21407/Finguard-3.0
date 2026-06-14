"""
Deterministic evaluation gate for Agent F (Tax Auditor).

Agent F's financial figures are computed by pure Python (`_calculate_tax_liability`
+ an AML threshold check), NOT by the LLM — the model only writes the narrative.
So these are fast, free, deterministic tests that **gate CI**: a wrong VAT/CIT
rate, threshold, or rounding rule fails the build before hallucination-free but
*arithmetically wrong* tax advice can ship.

(No LLM, no network. The companion `test_agent_f_narrative_judge.py` covers the
LLM-written narrative separately and is non-blocking.)
"""
from __future__ import annotations

import pytest

from src.domains.intelligence.agents.f_auditor import (
    _AML_REPORTING_THRESHOLD,
    _CIT_RATE,
    _VAT_RATE,
    _VAT_THRESHOLD_ANNUAL_KES,
    _calculate_tax_liability,
)
from tests.evals.datasets import AML_CASES, TAX_CASES, AmlCase, TaxCase


@pytest.mark.parametrize("case", TAX_CASES, ids=lambda c: c.id)
def test_tax_liability_matches_golden(case: TaxCase) -> None:
    tax_type, liability, etr = _calculate_tax_liability(
        case.revenue, case.opex, case.tax_regime, case.period_days
    )
    assert tax_type == case.expected_type, case.note
    # abs=0.01 (one cent) absorbs float-repr noise from round(_, 2) while still
    # catching any real logic regression, which is always off by ≥ thousands.
    assert liability == pytest.approx(case.expected_liability_kes, abs=0.01), case.note
    assert etr == pytest.approx(case.expected_etr_pct, abs=1e-4), case.note


@pytest.mark.parametrize("case", AML_CASES, ids=lambda c: c.id)
def test_aml_flag_threshold(case: AmlCase) -> None:
    flag = case.max_single_tx_kes >= _AML_REPORTING_THRESHOLD
    assert flag is case.expected_flag, case.note


def test_regulatory_constants_pinned() -> None:
    """Golden KRA figures — changing one must be a deliberate regulatory update.

    This is the test that catches silent drift like the KES 5M-vs-8M VAT
    threshold: the constants are pinned to their statutory values, so an edit to
    `f_auditor.py` that diverges fails CI rather than shipping wrong tax math.
    """
    assert _VAT_RATE == 0.16, "Kenya VAT standard rate is 16%"
    assert _CIT_RATE == 0.30, "Kenya resident CIT rate is 30%"
    assert _VAT_THRESHOLD_ANNUAL_KES == 5_000_000.0, "KRA mandatory VAT registration threshold"
    assert _AML_REPORTING_THRESHOLD == 1_000_000.0, "AML single-transaction reporting threshold"
