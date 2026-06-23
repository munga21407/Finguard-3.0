"""
Agent H — Financial Advisor: Generative UI component catalog.

This module supplies the prompt extension that teaches Gemini 2.5 Flash to emit
structured ``ui_widgets`` (see ``AgentHOutput``) alongside its narrative advice.
The catalog documents exactly the widgets the frontend ``GenUiRegistry`` can
render, so the model never invents a ``component_id`` the client can't mount.

``H_ADVISOR_ALLOWED_COMPONENTS`` is the single source of truth for which widgets
Agent H may emit; the node filters the model's output against it, and the
contract test asserts every entry exists in the frontend registry.
"""
from __future__ import annotations

# Widgets Agent H is allowed to emit. MUST stay a subset of the frontend
# GenUiRegistry keys (enforced by tests/integration/test_genui_contract.py).
H_ADVISOR_ALLOWED_COMPONENTS: frozenset[str] = frozenset(
    {
        "MiniTrendSparkline",
        "TransactionHistoryList",
        "SemiCircleGaugeCard",
    }
)


# The catalog + few-shot examples appended to the advisor system prompt.
H_ADVISOR_GENUI_CATALOG = """\
## Generative UI Component Catalog

When a figure is clearer shown than described, you MAY attach one or more UI
widgets in the `ui_widgets` array. Use ONLY the components below, and emit props
EXACTLY in the documented shape. If no widget adds value, return `ui_widgets: []`.
Never reference a component that is not listed here. Widgets supplement the
narrative — they never replace it, so `narrative_response` is always required.

### 1. MiniTrendSparkline
Use-case: show the recent direction of a single metric (revenue, burn, balance)
as a compact value + sparkline. Best for a short trailing series.
Props:
  - label (string)            — metric name, e.g. "Monthly Revenue"
  - value (string | number)   — the headline current value, e.g. "KES 1.5M"
  - data (number[])           — 4-12 trailing data points, oldest first
  - deltaPct (number, opt)    — period-over-period % change, e.g. 12.4 or -3.1
  - color (string, opt)       — accent hex, e.g. "#16a34a" for positive

### 2. TransactionHistoryList
Use-case: surface a handful of concrete transactions that justify a point
(e.g. the expenses driving a budget overrun, or recent large inflows).
Props:
  - title (string, opt)       — list heading, e.g. "Largest Outflows This Month"
  - transactions (object[])   — each: {
        name (string)           — counterparty / description,
        amount (number)         — magnitude in the given currency,
        currency (string, opt)  — ISO code, default "KES",
        type (string, opt)      — "Credit" | "Debit" | "Transfer",
        status (string, opt)    — "completed" | "pending" | "failed",
        datetime (string, opt)  — ISO-8601 timestamp
    }

### 3. SemiCircleGaugeCard
Use-case: show a single bounded reading against a capacity — utilisation,
a health/bankability score, or % of budget consumed.
Props:
  - title (string)            — what the gauge measures, e.g. "Budget Utilisation"
  - value (number)            — current reading
  - max (number, opt)         — capacity, default 100
  - unit (string, opt)        — suffix on the centre value, e.g. "%"
  - label (string, opt)       — caption under the value, e.g. "of monthly budget"
  - color (string, opt)       — accent hex

Every widget MUST also carry a `fallback_text` (a one-sentence plain-text
summary) so the client can degrade gracefully if the component fails to render.

## Few-shot examples

### Example A — budget overrun (gauge + driving transactions)
User intent: "Why is my spending so high this month?"
Assistant output (JSON):
{
  "narrative_response": "Your operating budget is **92% consumed** with 9 days left in the cycle, driven mainly by two large supplier payments. Consider deferring non-essential purchases until the next cycle to avoid an overrun.",
  "ui_widgets": [
    {
      "component_id": "SemiCircleGaugeCard",
      "props": {
        "title": "Budget Utilisation",
        "value": 92,
        "max": 100,
        "unit": "%",
        "label": "of monthly budget",
        "color": "#dc2626"
      },
      "fallback_text": "Budget utilisation is at 92% of the monthly allocation."
    },
    {
      "component_id": "TransactionHistoryList",
      "props": {
        "title": "Largest Outflows This Month",
        "transactions": [
          {"name": "Mombasa Supplies Ltd", "amount": 420000, "currency": "KES", "type": "Debit", "status": "completed", "datetime": "2026-06-14T09:20:00Z"},
          {"name": "Equity Bank — Loan Repayment", "amount": 180000, "currency": "KES", "type": "Debit", "status": "completed", "datetime": "2026-06-10T07:00:00Z"}
        ]
      },
      "fallback_text": "Two large debits totalling KES 600,000 drove most of the spend."
    }
  ]
}

### Example B — revenue trend (single sparkline)
User intent: "How has revenue been trending?"
Assistant output (JSON):
{
  "narrative_response": "Revenue has grown for **four straight months**, up about **12% month-on-month**, signalling healthy demand. Maintaining this trajectory would strengthen your bankability profile ahead of any financing application.",
  "ui_widgets": [
    {
      "component_id": "MiniTrendSparkline",
      "props": {
        "label": "Monthly Revenue",
        "value": "KES 1.5M",
        "data": [980000, 1050000, 1180000, 1320000, 1500000],
        "deltaPct": 12.4,
        "color": "#16a34a"
      },
      "fallback_text": "Monthly revenue is up ~12% to KES 1.5M, rising for four months."
    }
  ]
}
"""
