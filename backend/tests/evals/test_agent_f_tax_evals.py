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

from src.domains.intelligence.agents.f_auditor import _calculate_tax_liability
from src.domains.intelligence.tuning import AuditorTuning
from tests.evals.datasets import AML_CASES, TAX_CASES, AmlCase, TaxCase

# Statutory defaults (the tax rates/thresholds were externalised into
# AuditorTuning in Sprint 1; the golden tests pin the *default* values so a
# change to them is a deliberate regulatory update, and compute liabilities
# against those defaults regardless of any env/DB override in the test env).
_RATES = AuditorTuning()


@pytest.mark.parametrize("case", TAX_CASES, ids=lambda c: c.id)
def test_tax_liability_matches_golden(case: TaxCase) -> None:
    tax_type, liability, etr = _calculate_tax_liability(
        case.revenue, case.opex, case.tax_regime, case.period_days, _RATES
    )
    assert tax_type == case.expected_type, case.note
    # abs=0.01 (one cent) absorbs float-repr noise from round(_, 2) while still
    # catching any real logic regression, which is always off by ≥ thousands.
    assert liability == pytest.approx(case.expected_liability_kes, abs=0.01), case.note
    assert etr == pytest.approx(case.expected_etr_pct, abs=1e-4), case.note


@pytest.mark.parametrize("case", AML_CASES, ids=lambda c: c.id)
def test_aml_flag_threshold(case: AmlCase) -> None:
    flag = case.max_single_tx_kes >= _RATES.aml_reporting_threshold_kes
    assert flag is case.expected_flag, case.note


def test_regulatory_constants_pinned() -> None:
    """Golden KRA figures — changing one must be a deliberate regulatory update.

    This is the test that catches silent drift like the KES 5M-vs-8M VAT
    threshold: the AuditorTuning defaults are pinned to their statutory values, so
    an edit that diverges fails CI rather than shipping wrong tax math.
    """
    assert _RATES.vat_rate == 0.16, "Kenya VAT standard rate is 16%"
    assert _RATES.cit_rate == 0.30, "Kenya resident CIT rate is 30%"
    assert _RATES.vat_threshold_annual_kes == 5_000_000.0, "KRA mandatory VAT registration threshold"
    assert _RATES.aml_reporting_threshold_kes == 1_000_000.0, "AML single-transaction threshold"
