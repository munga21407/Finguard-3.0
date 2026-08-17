"""
Agent H — Financial Advisor: Generative UI component catalog.

This module supplies the prompt extension that teaches Gemma 4 to emit
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
        # Sprint 8 — variant-driven widget families (one component_id, many
        # named `variant`s; see H_ADVISOR_GENUI_CATALOG for the enum per family).
        "ChartXY",
        "ChartPie",
        "ChartWordcloud",
        "RankedList",
        "QuadrantGrid",
        "SequenceFlow",
        "CompareBinary",
        "HierarchyTree",
        "RelationGraph",
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

### 4. ChartXY
Use-case: categories x one-or-more series. `variant` picks the geometry —
"column" (vertical bars, default), "bar" (horizontal bars), "line" (trend line(s)).
Props:
  - title (string, opt)
  - variant ("bar" | "column" | "line", opt, default "column")
  - categories (string[])      — x-axis labels
  - series (object[])          — each: { name (string), color (string, opt hex), values (number[], one per category) }

### 5. ChartPie
Use-case: a whole broken into named shares (revenue by category, expense mix).
Props:
  - title (string, opt)
  - data (object[])            — each: { name (string), value (number), color (string, opt hex) }
  - donut (boolean, opt, default true)
  - unit (string, opt)         — suffix on the centred total, e.g. "KES"

### 6. ChartWordcloud
Use-case: relative importance/frequency of terms (invoice line-item keywords,
support ticket topics). Not for precise magnitude comparison — use ChartXY for that.
Props:
  - title (string, opt)
  - terms (object[])           — each: { text (string), weight (number, positive) }

### 7. RankedList
Use-case: an ordered set of labelled values. `variant` picks the layout —
"row" (leaderboard bars, default), "column" (vertical bars), "grid" (card tiles),
"pyramid" (widest = highest value), "sector" (ringed around a hub),
"waterfall" (running-total bridge — value is the delta, not the level),
"zigzag" (alternating timeline cards).
Props:
  - title (string, opt)
  - variant ("column"|"grid"|"pyramid"|"row"|"sector"|"waterfall"|"zigzag", opt, default "row")
  - items (object[])           — each: { label (string), value (number), description (string, opt) }

### 8. QuadrantGrid
Use-case: framing something on two axes or four labelled buckets. `variant`
"quarter" scatters points on an x/y grid; "simple" | "compare" | "swot" show four
labelled cells (no points) — "swot" pre-labels them Strengths/Weaknesses/Opportunities/Threats.
Props:
  - title (string, opt)
  - variant ("quarter"|"simple"|"compare"|"swot", opt, default "simple")
  - xLabel, yLabel (string, opt) — "quarter" axis captions
  - points (object[], "quarter" only) — each: { label (string), x (number 0-100), y (number 0-100), color (string, opt) }
  - quadrants (exactly 4 objects, all variants except "quarter") — each: { label (string), description (string, opt), items (string[], opt) }, order = [top-left, top-right, bottom-left, bottom-right]

### 9. SequenceFlow
Use-case: an ORDERED progression of steps (a process, a funnel, a timeline, stages
of anything). `variant` is purely cosmetic — pick whichever best matches the intent:
"timeline" | "horizontal" | "steps" | "stairs" | "ascending" | "funnel" | "filter" |
"pyramid" | "mountain" | "cylinders" | "roadmap" | "snake" | "zigzag" | "circle" |
"circular" (closed loop) | "color" (spectrum bar) | "interaction" (clickable stepper).
Props:
  - title (string, opt)
  - variant (one of the strings above, opt, default "steps")
  - steps (object[])           — each: { label (string), value (number, opt), description (string, opt), color (string, opt) }

### 10. CompareBinary
Use-case: a head-to-head decision between exactly two options (loan A vs loan B,
lease vs buy).
Props:
  - title (string, opt)
  - left, right (object)       — each: { label (string), points: [{ text (string), positive (boolean, opt — true=pro, false=con, omit=neutral) }] }
  - winner ("left"|"right", opt) — highlights that column
  - verdict (string, opt)      — one-sentence recommendation banner

### 11. HierarchyTree
Use-case: a nested breakdown (org chart, expense category tree, a mind map of
ideas). `variant` "mindmap" | "structure" | "tree" render one `root`; "compare"
renders two independent trees side by side from `roots`.
Props:
  - title (string, opt)
  - variant ("mindmap"|"structure"|"tree"|"compare", opt, default "tree")
  - root (object, all variants except "compare") — { label (string), value (string|number, opt), children (recursive HierarchyNode[], opt) }
  - roots (exactly 2 objects, "compare" only) — same node shape as `root`

### 12. RelationGraph
Use-case: named entities and how they relate (dependency chains, referral
networks, ownership structures). Keep it small — this renders in a chat card,
not a graph editor; 3-12 nodes reads well, more gets cramped.
Props:
  - title (string, opt)
  - variant ("circle"|"dagre"|"network", opt, default "network") — "dagre" implies directed/hierarchical (use when edges represent a flow or dependency); "circle"/"network" are undirected relationship layouts
  - nodes (object[])           — each: { id (string, unique), label (string), group (number, opt — colors nodes by group) }
  - edges (object[])           — each: { source (string, matches a node id), target (string, matches a node id), label (string, opt) }

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

### Example C — expense mix by category (pie) + top vendors (ranked list)
User intent: "Where is my money actually going this quarter?"
Assistant output (JSON):
{
  "narrative_response": "Payroll and inventory purchases together account for **68% of Q2 spend**. Inventory is the single largest line — worth reviewing supplier terms before Q3.",
  "ui_widgets": [
    {
      "component_id": "ChartPie",
      "props": {
        "title": "Q2 Expense Mix",
        "data": [
          {"name": "Inventory", "value": 620000},
          {"name": "Payroll", "value": 480000},
          {"name": "Rent", "value": 150000},
          {"name": "Utilities", "value": 90000}
        ],
        "unit": "KES"
      },
      "fallback_text": "Inventory (620K) and payroll (480K) drove most of Q2 spend."
    },
    {
      "component_id": "RankedList",
      "props": {
        "title": "Top Vendors by Spend",
        "variant": "row",
        "items": [
          {"label": "Mombasa Supplies Ltd", "value": 310000},
          {"label": "Staff Payroll Run", "value": 480000},
          {"label": "Nairobi Logistics Co", "value": 210000}
        ]
      },
      "fallback_text": "Payroll, then Mombasa Supplies Ltd, were the largest individual spend items."
    }
  ]
}

### Example D — loan payoff process (sequence funnel)
User intent: "Walk me through the steps to clear this loan early."
Assistant output (JSON):
{
  "narrative_response": "Clearing the loan 6 months early needs three moves, in order: build a KES 150K buffer, negotiate the early-settlement figure, then execute the payoff. Each stage below assumes the prior one is done first.",
  "ui_widgets": [
    {
      "component_id": "SequenceFlow",
      "props": {
        "title": "Early Payoff Plan",
        "variant": "funnel",
        "steps": [
          {"label": "Build KES 150K buffer", "value": 150000, "description": "3 months of set-asides from operating cash flow"},
          {"label": "Negotiate settlement figure", "value": 140000, "description": "Request early-settlement quote from the lender"},
          {"label": "Execute payoff", "value": 135000, "description": "Wire the negotiated amount, request a discharge letter"}
        ]
      },
      "fallback_text": "Three-step payoff plan: build a KES 150K buffer, negotiate the settlement figure, then execute."
    }
  ]
}
"""
