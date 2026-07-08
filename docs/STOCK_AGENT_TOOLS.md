# Stock Agent — Tool Design Guide

*Companion to [`STOCK_MANAGEMENT_MODULE.md`](./STOCK_MANAGEMENT_MODULE.md).
Defines the agent that reasons over SKUs / stock and the **toolset** it should
be given — grounded in Finguard's existing agent-tool conventions
(`src/domains/intelligence/tools/*`, the LangChain `@tool` + `@traced_tool`
factory pattern, the read-only masked SQL executor, and the
`agent_registry` / supervisor wiring).*

> **The agent:** a new intelligence agent — **Agent K, the "Stock Steward"**
> (`agent_id = "K"`, node `k_stockkeeper`, intent `inventory`). It answers stock
> questions, spots reorder/stockout risk, forecasts demand, values inventory, and
> *proposes* stock corrections — over the `inventory` domain's `products` /
> `stock_levels` / `stock_movements` tables.

---

## 1. First principles (non-negotiable, inherited from the codebase)

These decide *what kind* of tool each capability gets. They come straight from
patterns already enforced in `tools/sql_executor.py`, Agent D (Text-to-SQL CoVe),
Agent F (deterministic tax gates), and Agent H (S6-5 review gate).

1. **Reads use a read-only, allowlist-masked path.** The agent never sees an
   unrestricted DB handle. Analytical reads go through the existing
   `make_readonly_sql_executor` (bound to the `finguard_readonly` role) with the
   inventory tables added to the per-agent allowlist — or through *typed* read
   tools for the hot paths. Schema masking + the structural AST allowlist stop a
   hallucinated/injected query from touching `users`, `knowledge_base`, etc.
2. **Writes NEVER go through LLM-authored SQL.** A stock mutation is a
   money-adjacent, ledger-guarded operation. The agent's only write path is a
   **typed tool that calls `InventoryService.apply_movement`** — so the
   non-negative guard, weighted-average costing, per-product `FOR UPDATE` lock,
   sequence, and audit all still apply. The LLM supplies *parameters*, never SQL.
3. **Propose, don't apply, by default.** Concrete stock changes are "actionable"
   in the S6-5 sense. The write tool returns a **proposed** movement for operator
   confirmation and is gated on `INTELLIGENCE_ACT` + the human-review gate; it
   only auto-applies when an operator has explicitly authorised it.
4. **Deterministic math beats LLM estimation.** Reorder points, EOQ, valuation,
   days-of-cover are arithmetic — compute them in a Python tool and hand the LLM
   the numbers. The LLM narrates and prioritises; it does not invent figures
   (same contract as Agent H's "do NOT alter any numbers").
5. **Every tool is observable and every action is audited.** Wrap tools in
   `@traced_tool("...")` like `http_caller` / `sql_executor`; route write
   confirmations through `AuditService.record_user_action_safe`.

---

## 2. Tool catalog

Risk tiers: **R** = read-only (safe), **C** = compute (pure, safe),
**W** = write/side-effecting (gated). "Reuse" = an existing tool (extend its
allowlist); "New" = build in `tools/`.

| # | Tool | Tier | Source | Permission | Human-in-loop |
|---|---|---|---|---|---|
| 1 | `stock_level_lookup` | R | New (typed) | `INVENTORY_READ` | no |
| 2 | `movement_history` | R | New (typed) | `INVENTORY_READ` | no |
| 3 | `inventory_sql_readonly` | R | **Reuse** `make_readonly_sql_executor` (+allowlist) | `INVENTORY_READ` | no |
| 4 | `low_stock_report` | R | New (typed, wraps service) | `INVENTORY_READ` | no |
| 5 | `inventory_valuation` | C | New (pure calc over levels) | `INVENTORY_READ` | no |
| 6 | `reorder_recommendation` | C | New (pure calc) | `INVENTORY_READ` | no |
| 7 | `demand_forecast` | C | **Reuse** Agent D forecasting primitives | `INVENTORY_READ` | no |
| 8 | `propose_stock_movement` | W | New → `InventoryService.apply_movement` | `INTELLIGENCE_ACT` | **yes** |
| 9 | `raise_stock_alert` | W (low) | **Reuse** `alerts.create_alert_idempotent` | `INTELLIGENCE_ACT` | no (idempotent) |
| 10 | `receipt_ocr` | R | **Reuse** `tools/vision_ocr.extract_receipt` | `INVENTORY_READ` | yes (confirm) |

### 2.1 Read tools

**1. `stock_level_lookup(sku | product_id) -> StockLevelView`** — the hot path.
A typed query (not free SQL) returning on-hand, reserved, average cost, reorder
level, and days-of-cover for one product. Prefer this over SQL for the common
"how much X do we have?" question — it's cheaper, un-injectable, and testable.

**2. `movement_history(product_id, limit=50) -> list[MovementRow]`** — the
append-only ledger for one product (the "why is on-hand 7?" audit trail and the
series demand-forecast consumes). Typed, ordered by `sequence` desc.

**3. `inventory_sql_readonly(query) -> rows`** — **reuse** the existing
read-only executor for ad-hoc analytics (cross-product aggregates, category
rollups, slow-movers). To enable it for Agent K:
- Add to `tools/sql_executor.py::_AGENT_ALLOWED_TABLES`:
  ```python
  "K": frozenset({"products", "stock_levels", "stock_movements"}),
  ```
- Add the three tables' DDL to `_TABLE_DDL` so `get_masked_schema("K")` renders
  them for the prompt. The union allowlist then admits them structurally.
- The executor already rejects any non-SELECT and any table outside the
  allowlist at the AST level — no new safety code needed.

**4. `low_stock_report() -> list[LowStockItem]`** — products at/below
`reorder_level`; wraps the same service method the `/inventory/reports/low-stock`
endpoint uses (one source of truth).

### 2.2 Compute tools (pure, deterministic)

**5. `inventory_valuation(by_category=False) -> ValuationReport`** —
`Σ(on_hand × average_cost)`; optional per-category breakdown. Pure arithmetic
over `stock_levels`.

**6. `reorder_recommendation(product_id) -> ReorderPlan`** — deterministic:
`reorder_point = avg_daily_usage × lead_time_days + safety_stock`; suggested
order qty from EOQ or the product's `reorder_quantity`. Returns numbers; the LLM
explains urgency. Keep the formula/constants in `inventory` tuning-style config
so they're tunable without a deploy (mirror the S1 tuning pattern).

**7. `demand_forecast(product_id, horizon_days) -> Forecast`** — **reuse** Agent
D's forecasting primitives (the statsmodels path already in the codebase) over
the movement series from tool #2, rather than a bespoke model. Returns projected
consumption + confidence; degrades gracefully on thin history (like Agent E's
`on_the_fly` degraded flag).

### 2.3 Write / action tools (gated)

**8. `propose_stock_movement(product_id, movement_type, quantity, reason?,
unit_cost?) -> ProposedMovement | AppliedMovement`** — the **only** mutation
path. Contract:
- Validates params against the same rules the schema enforces (`quantity > 0`,
  `unit_cost` required for `RECEIPT`, `reason` required for `ADJUSTMENT`).
- Calls `InventoryService.apply_movement` — so it inherits the row lock, the
  non-negative guard, sequence, weighted-avg costing, and `balance_after`.
  **Never** emits SQL.
- **Default = propose:** returns a structured proposal (what/why/resulting
  on-hand) and does *not* commit unless `context["require_stock_confirmation"]`
  is satisfied or an operator has pre-authorised (S6-5 review-gate pattern).
- On apply: writes an audit row (`STOCK_ADJUSTED` / `STOCK_ISSUED` …) with the
  agent as actor (`AuditActorType.AGENT`).
- Gated on `INTELLIGENCE_ACT`; a read-only session/role can only ever *propose*.

**9. `raise_stock_alert(product_id, kind)` — reuse**
`AlertService.create_alert_idempotent` keyed on `(product_id, kind)` so repeated
runs don't spam. Fire on a detected stockout/low-stock condition.

**10. `receipt_ocr(image) -> ReceiptExtraction` — reuse**
`tools/vision_ocr.extract_receipt` to read a supplier delivery note / purchase
receipt, then feed a **proposed** `RECEIPT` movement (tool #8) for operator
confirmation. This is how restocking gets a low-friction, human-verified entry
point — and it benefits from the S6-6 multi-pass higher-fidelity retry for free.

---

## 3. Explicitly *not* given to this agent

Being deliberate about the negative space is part of the design:
- **No raw/writable DB handle, no `INSERT/UPDATE/DELETE` SQL tool.** All mutation
  is tool #8 through the service. (This is why #3 uses the *read-only* executor.)
- **No access to `users`, `knowledge_base`, `outbox_events`, or finance money
  tables** — the SQL allowlist for `"K"` is only the three inventory tables. If
  the agent needs COGS, it asks finance's read method, it doesn't query
  `invoices` directly.
- **No direct `http_caller` in v1** unless a concrete supplier-price/catalog
  integration is scoped — outbound HTTP widens the attack surface (SSRF) and is
  only worth it with a real use case. Add it later behind the same pinned-IP
  `make_http_caller` used by Agent I.
- **No auto-apply of destructive adjustments.** Writing off stock (DAMAGE/THEFT)
  always proposes → human confirms.

---

## 4. Wiring the agent + tools into the platform

1. **Tools:** add `tools/inventory_tools.py` with the `make_*` factories for
   #1/#2/#4/#5/#6/#8/#9 (each `@traced_tool("stock_*")`), and extend
   `sql_executor.py`'s allowlist + `_TABLE_DDL` for #3.
2. **Agent node:** `agents/k_stockkeeper.py` — a LangGraph node that (a) resolves
   RBAC role (reuse Agent H's `_resolve_user_role`), (b) binds the read/compute
   tools always and the write tool only when `INTELLIGENCE_ACT` is granted,
   (c) uses Gemini structured output for the narrative + a structured
   `proposed_actions` list, never free-form numbers.
3. **Registry:** one `AgentDescriptor` in `agent_registry.py`
   (`agent_id="K"`, `context_key="inventory_analysis"`, `intent="inventory"`,
   a TTL + `summary_order`) — `hub_writer` and Agent J then pick it up with no
   further edits (that's the Sprint-2 contract).
4. **Supervisor routing:** add a `_KEYWORD_ROUTES` entry in `supervisor.py` so
   clear intents skip the Gemini routing call (0-cost route, per Sprint 3):
   ```python
   ("k_stockkeeper", frozenset({"stock", "inventory", "sku", "reorder",
                                "stock level", "out of stock", "restock"})),
   ```
   and add `"k_stockkeeper"` to `VALID_NEXT`.
5. **Permissions:** the read/compute tools need `INVENTORY_READ`; the write tool
   needs `INTELLIGENCE_ACT` (state-changing agent action) *and* the operator's
   own inventory-write authority — enforce both in the service call.

---

## 5. Safety, evals & acceptance

- **Structural, not prompt-only, safety:** the read allowlist and the
  no-LLM-SQL-for-writes rule are enforced in code, so a prompt injection that
  says "delete all stock" produces at most a *rejected* SELECT or a *proposed*
  movement a human must confirm — never a silent write.
- **Deterministic gates (Sprint-4 style):** unit-test that `propose_stock_movement`
  refuses to apply an `ISSUE` beyond on-hand and that an `ADJUSTMENT` without a
  reason is rejected — independent of what the LLM said.
- **Eval fixtures (Sprint-4 style):** a labeled set of stock questions →
  expected tool call + expected on-hand/valuation, run hermetically with the LLM
  mocked, plus a nightly accuracy judge for the narrative.
- **Acceptance:** the agent answers stock queries from typed tools / masked SQL
  only; it can never mutate stock without the service guard + (for actionable
  changes) human confirmation; every applied movement has an agent-attributed
  audit row; reorder/valuation figures come from deterministic tools, not the
  model.
