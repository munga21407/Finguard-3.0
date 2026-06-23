"""Pure builders for the CoreReports financial reports.

These functions take already-aggregated figures (the service runs the SQL) and
shape them into ``FinancialReport`` objects.  Keeping the arithmetic pure means
the P&L / cash-flow / tax math is unit-tested without a database.

Every figure is derived from live ledger/invoice data — nothing is fabricated.
Tax figures that depend on assumptions (the corporate rate) are flagged
``is_estimate=True`` so the UI can label them honestly.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from src.domains.finance.schemas import (
    FinancialReport,
    ReportLine,
    ReportMetric,
    ReportSeriesPoint,
    ReportType,
)

# Kenya VAT standard rate and resident corporate income-tax rate.  The VAT figure
# itself comes from each invoice's stored ``tax`` column; the corporate rate is
# only applied to produce a clearly-labelled income-tax *estimate*.
CORPORATE_TAX_RATE = Decimal("0.30")

_CENTS = Decimal("0.01")


def _money(value: Decimal) -> Decimal:
    return Decimal(value).quantize(_CENTS)


def _pct(numerator: Decimal, denominator: Decimal) -> Decimal:
    if denominator == 0:
        return Decimal("0.00")
    return (numerator / denominator * 100).quantize(_CENTS)


# Aggregate inputs are oldest-first ``(month, revenue, opex)`` triples plus the
# per-category breakdowns; the service supplies them straight from SQL.
MonthlyRows = list[tuple[str, Decimal, Decimal]]
CategoryRows = list[tuple[str, Decimal]]


def _series(monthly: MonthlyRows, keys: tuple[str, str]) -> list[ReportSeriesPoint]:
    rev_key, opex_key = keys
    return [
        ReportSeriesPoint(
            period=month,
            values={rev_key: _money(rev), opex_key: _money(opex)},
        )
        for month, rev, opex in monthly
    ]


def build_income_statement(
    *,
    monthly: MonthlyRows,
    expense_categories: CategoryRows,
    period_days: int,
    now: datetime,
) -> FinancialReport:
    revenue = sum((r for _, r, _ in monthly), Decimal("0"))
    opex = sum((o for _, _, o in monthly), Decimal("0"))
    net = revenue - opex

    summary = [
        ReportMetric(label="Revenue", value=_money(revenue)),
        ReportMetric(label="Operating Expenses", value=_money(opex)),
        ReportMetric(label="Net Profit", value=_money(net)),
        ReportMetric(label="Net Margin", value=_pct(net, revenue), unit="%"),
    ]
    lines = [
        ReportLine(label=cat or "Uncategorised", amount=_money(amt))
        for cat, amt in expense_categories
    ]
    return FinancialReport(
        report_type=ReportType.INCOME_STATEMENT,
        title="Income Statement",
        period_days=period_days,
        generated_at=now,
        has_data=bool(revenue or opex),
        summary=summary,
        lines=lines,
        series=_series(monthly, ("revenue", "expenses")),
    )


def build_cash_flow(
    *,
    monthly: MonthlyRows,
    period_days: int,
    now: datetime,
) -> FinancialReport:
    inflow = sum((r for _, r, _ in monthly), Decimal("0"))
    outflow = sum((o for _, _, o in monthly), Decimal("0"))
    net = inflow - outflow
    months = len(monthly) or 1
    avg_burn = outflow / months

    summary = [
        ReportMetric(label="Total Inflows", value=_money(inflow)),
        ReportMetric(label="Total Outflows", value=_money(outflow)),
        ReportMetric(label="Net Cash Flow", value=_money(net)),
        ReportMetric(label="Avg Monthly Burn", value=_money(avg_burn)),
    ]
    series = [
        ReportSeriesPoint(
            period=month,
            values={
                "inflows": _money(rev),
                "outflows": _money(opex),
                "net": _money(rev - opex),
            },
        )
        for month, rev, opex in monthly
    ]
    return FinancialReport(
        report_type=ReportType.CASH_FLOW,
        title="Cash Flow",
        period_days=period_days,
        generated_at=now,
        has_data=bool(inflow or outflow),
        summary=summary,
        lines=[],
        series=series,
    )


def build_tax_liability(
    *,
    monthly: MonthlyRows,
    output_vat: Decimal,
    period_days: int,
    now: datetime,
) -> FinancialReport:
    revenue = sum((r for _, r, _ in monthly), Decimal("0"))
    opex = sum((o for _, _, o in monthly), Decimal("0"))
    taxable_income = revenue - opex
    est_income_tax = (
        _money(max(taxable_income, Decimal("0")) * CORPORATE_TAX_RATE)
    )

    summary = [
        ReportMetric(label="VAT Payable (output)", value=_money(output_vat)),
        ReportMetric(label="Taxable Income", value=_money(taxable_income), is_estimate=True),
        ReportMetric(
            label="Estimated Income Tax",
            value=est_income_tax,
            is_estimate=True,
        ),
        ReportMetric(
            label="Corporate Rate",
            value=(CORPORATE_TAX_RATE * 100).quantize(_CENTS),
            unit="%",
            is_estimate=True,
        ),
    ]
    lines = [
        ReportLine(label="Output VAT (on sales)", amount=_money(output_vat)),
        ReportLine(label="Estimated Income Tax", amount=est_income_tax),
    ]
    return FinancialReport(
        report_type=ReportType.TAX_LIABILITY,
        title="Tax Liability",
        period_days=period_days,
        generated_at=now,
        has_data=bool(output_vat or revenue),
        summary=summary,
        lines=lines,
        series=_series(monthly, ("revenue", "expenses")),
    )
