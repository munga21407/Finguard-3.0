"""CoreReports builders — P&L / cash-flow / tax math (hermetic, no DB).

The service runs the SQL; these pure builders turn the aggregates into reports,
so the arithmetic (net profit, margin, burn, VAT, estimated income tax) is
verified here without a database.
"""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from src.domains.finance.reports import (
    CORPORATE_TAX_RATE,
    build_cash_flow,
    build_income_statement,
    build_tax_liability,
)
from src.domains.finance.schemas import ReportType

_NOW = datetime(2026, 6, 23, tzinfo=UTC)

# Two months: revenue then opex.
_MONTHLY = [
    ("2026-05", Decimal("1000.00"), Decimal("600.00")),
    ("2026-06", Decimal("1500.00"), Decimal("900.00")),
]


def _metric(report, label: str) -> Decimal:
    return next(m.value for m in report.summary if m.label == label)


def test_income_statement_net_and_margin() -> None:
    report = build_income_statement(
        monthly=_MONTHLY,
        expense_categories=[("Rent", Decimal("900.00")), ("Salaries", Decimal("600.00"))],
        period_days=365,
        now=_NOW,
    )
    assert report.report_type == ReportType.INCOME_STATEMENT
    assert report.has_data is True
    assert _metric(report, "Revenue") == Decimal("2500.00")
    assert _metric(report, "Operating Expenses") == Decimal("1500.00")
    assert _metric(report, "Net Profit") == Decimal("1000.00")
    assert _metric(report, "Net Margin") == Decimal("40.00")
    assert len(report.series) == 2
    assert report.series[0].values["revenue"] == Decimal("1000.00")


def test_cash_flow_net_and_burn() -> None:
    report = build_cash_flow(monthly=_MONTHLY, period_days=365, now=_NOW)
    assert _metric(report, "Total Inflows") == Decimal("2500.00")
    assert _metric(report, "Total Outflows") == Decimal("1500.00")
    assert _metric(report, "Net Cash Flow") == Decimal("1000.00")
    assert _metric(report, "Avg Monthly Burn") == Decimal("750.00")
    assert report.series[1].values["net"] == Decimal("600.00")


def test_tax_liability_vat_and_income_tax_estimate() -> None:
    report = build_tax_liability(
        monthly=_MONTHLY,
        output_vat=Decimal("400.00"),
        period_days=365,
        now=_NOW,
    )
    assert _metric(report, "VAT Payable (output)") == Decimal("400.00")
    # Taxable income = 2500 - 1500 = 1000; income tax = 1000 * 0.30.
    assert _metric(report, "Estimated Income Tax") == (
        Decimal("1000.00") * CORPORATE_TAX_RATE
    ).quantize(Decimal("0.01"))
    # Estimates are flagged so the UI can label them.
    assert any(m.is_estimate for m in report.summary)


def test_negative_profit_yields_zero_income_tax() -> None:
    loss = [("2026-06", Decimal("100.00"), Decimal("500.00"))]
    report = build_tax_liability(
        monthly=loss, output_vat=Decimal("0"), period_days=365, now=_NOW
    )
    assert _metric(report, "Estimated Income Tax") == Decimal("0.00")


def test_empty_inputs_report_no_data() -> None:
    report = build_income_statement(
        monthly=[], expense_categories=[], period_days=365, now=_NOW
    )
    assert report.has_data is False
    assert _metric(report, "Net Margin") == Decimal("0.00")
