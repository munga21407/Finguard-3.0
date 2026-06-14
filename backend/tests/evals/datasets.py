"""Golden evaluation scenarios for Agent F (Tax Auditor).

These are the **expected** outcomes derived from Kenya tax law — NOT from the
code under test. Expected values are hand-computed and hardcoded so that a silent
change to a rate or threshold in ``f_auditor.py`` (e.g. the KES 5M vs 8M VAT
discrepancy that motivated this harness) fails the build instead of slipping
through. Keep the arithmetic in ``note`` so a reviewer can re-derive each figure.

Tax rules encoded:
  * VAT  = 16% of period revenue, but only when *annualised* revenue ≥ KES 5M.
  * CIT  = 30% of net profit (revenue − opex), floored at 0 for a loss.
  * COMPREHENSIVE (default/fallback regime) = VAT + CIT combined.
  * Effective tax rate (ETR) = tax_liability / revenue × 100.
  * AML single-transaction reporting threshold = KES 1,000,000 (inclusive).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TaxCase:
    id: str
    revenue: float
    opex: float
    tax_regime: str
    period_days: int
    expected_type: str
    expected_liability_kes: float
    expected_etr_pct: float
    note: str


TAX_CASES: list[TaxCase] = [
    TaxCase(
        id="vat_above_threshold_full_year",
        revenue=10_000_000, opex=4_000_000, tax_regime="VAT", period_days=365,
        expected_type="VAT", expected_liability_kes=1_600_000.0, expected_etr_pct=16.0,
        note="annual 10M ≥ 5M → VAT 10M×0.16=1.6M; ETR 1.6M/10M=16%",
    ),
    TaxCase(
        id="vat_below_threshold_full_year",
        revenue=4_000_000, opex=1_000_000, tax_regime="VAT", period_days=365,
        expected_type="VAT", expected_liability_kes=0.0, expected_etr_pct=0.0,
        note="annual 4M < 5M → no VAT due",
    ),
    TaxCase(
        id="vat_exactly_at_threshold",
        revenue=5_000_000, opex=0, tax_regime="VAT", period_days=365,
        expected_type="VAT", expected_liability_kes=800_000.0, expected_etr_pct=16.0,
        note="annual 5M ≥ 5M (inclusive) → VAT 5M×0.16=800k",
    ),
    TaxCase(
        id="vat_annualisation_crosses_threshold",
        revenue=1_500_000, opex=500_000, tax_regime="VAT", period_days=90,
        expected_type="VAT", expected_liability_kes=240_000.0, expected_etr_pct=16.0,
        note="annualised 1.5M×(365/90)=6.08M ≥ 5M → VAT on *period* revenue 1.5M×0.16=240k",
    ),
    TaxCase(
        id="vat_annualisation_stays_below",
        revenue=300_000, opex=100_000, tax_regime="VAT", period_days=30,
        expected_type="VAT", expected_liability_kes=0.0, expected_etr_pct=0.0,
        note="annualised 300k×(365/30)=3.65M < 5M → no VAT",
    ),
    TaxCase(
        id="cit_profitable",
        revenue=8_000_000, opex=5_000_000, tax_regime="CORPORATE_TAX", period_days=365,
        expected_type="CORPORATE_TAX", expected_liability_kes=900_000.0, expected_etr_pct=11.25,
        note="net 3M × 0.30 = 900k; ETR 900k/8M=11.25%",
    ),
    TaxCase(
        id="cit_loss_floored_at_zero",
        revenue=2_000_000, opex=3_000_000, tax_regime="CIT", period_days=365,
        expected_type="CORPORATE_TAX", expected_liability_kes=0.0, expected_etr_pct=0.0,
        note="net max(2M-3M,0)=0 → no CIT; 'CIT' alias resolves to CORPORATE_TAX",
    ),
    TaxCase(
        id="comprehensive_above_threshold_with_profit",
        revenue=12_000_000, opex=7_000_000, tax_regime="COMPREHENSIVE", period_days=365,
        expected_type="COMPREHENSIVE", expected_liability_kes=3_420_000.0, expected_etr_pct=28.5,
        note="VAT 12M×0.16=1.92M + CIT (5M×0.30=1.5M) = 3.42M; ETR 3.42M/12M=28.5%",
    ),
    TaxCase(
        id="unknown_regime_falls_back_to_comprehensive_below_vat",
        revenue=4_000_000, opex=1_000_000, tax_regime="SOMETHING_ELSE", period_days=365,
        expected_type="COMPREHENSIVE", expected_liability_kes=900_000.0, expected_etr_pct=22.5,
        note="unknown regime → COMPREHENSIVE; annual 4M < 5M so VAT 0 + CIT 3M×0.30=900k; ETR 22.5%",
    ),
    TaxCase(
        id="regime_case_insensitive_lowercase_vat",
        revenue=6_000_000, opex=0, tax_regime="vat", period_days=365,
        expected_type="VAT", expected_liability_kes=960_000.0, expected_etr_pct=16.0,
        note="lowercase 'vat' upper-cased; annual 6M ≥ 5M → 6M×0.16=960k",
    ),
]


@dataclass(frozen=True)
class AmlCase:
    id: str
    max_single_tx_kes: float
    expected_flag: bool
    note: str


AML_CASES: list[AmlCase] = [
    AmlCase("at_threshold_inclusive", 1_000_000.0, True, "threshold is inclusive (≥)"),
    AmlCase("just_below_threshold", 999_999.99, False, "1 cent under → no flag"),
    AmlCase("well_above_threshold", 1_500_000.0, True, "clearly reportable"),
    AmlCase("no_large_transaction", 0.0, False, "empty ledger → no flag"),
]
