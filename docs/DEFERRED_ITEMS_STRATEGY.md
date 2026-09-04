# Deferred Items — Implementation Strategy

*Companion to [`AGENTS_REMEDIATION_SPRINTS.md`](./AGENTS_REMEDIATION_SPRINTS.md).
Five items were deferred during Sprints 1–3, each for a concrete reason (needs a
live DB, changes locking semantics, or is deployment config). This is the
how-to-land-them plan, grounded in the existing code patterns.*

| # | Item | From | Effort | Status |
|---|---|---|---|---|
| A | Admin HTTP router for tuning / tax rates | S1 | S–M | ✅ **DONE** (`routers/admin_tuning.py`) |
| B | DB-integration tests (agent_config, tax schedule) | S1 | S | ✅ **DONE** (`tests/integration/`) |
| C | Receipt scanner → single vision call | S3-3 | S | ✅ **DONE** |
| D | Agent C SQL candidate pushdown + indexes | S3-4 | L | ◑ **indexes DONE; code pushdown deferred** |
| E | Grafana dashboard panels | S3-6 | S | ✅ **DONE** |

> **D — indexes shipped, code pushdown deferred with a de-risked spec.**
> Migration `0016` adds the three fetch-supporting indexes (`mpesa_transactions`,
> `invoices`, `bank_statement_lines`). **Key finding:** `apply_reconciled_payment`
> already locks each invoice `FOR UPDATE` and clamps to the outstanding balance
> (returns None if settled) — so double-settle is impossible and the up-front
> invoice lock is an *optimisation*, not a safety requirement. That makes the
> candidate-join pushdown safe to add; the exact `FOR UPDATE OF i SKIP LOCKED`
> query + lazy-Pass-2 plan is now documented in `services/reconciliation_service.py`'s
> module docstring as a turn-key spec (moved there from `c_reconciler.py` in
> Sprint 8's agent-decomposition pass — see `AGENTS_REMEDIATION_SPRINTS.md` §Sprint 8).
> The code rewrite itself is **not shipped** because it's the money
> path and can't be validated without a live DB, and its benefit is bounded (the
> invoice fetch is already capped at `_INV_LIMIT=500` and the amount-bucketing
> already fixed the O(txn×invoice) compute). Recommended: implement behind a config
> flag and validate match-equivalence + concurrency against Postgres before making
> it default.

> **C + E landed.** C: `ReceiptExtraction` gained a `suggested_category` field
> (schema-validated to the 5-value taxonomy, now shared in `schemas.py`); the
> `extract_receipt` vision prompt classifies in the **same call**; the classifier
> node is now a no-LLM guard → **1 LLM call per scan (was 2)**. Human-in-loop
> fallback preserved. Verified: `test_receipt_scan.py` 4/4 pass (ran locally, no
> DB needed). E: added two panels to `monitoring/dashboards/finguard_ai_overview.json`
> — "Supervisor Routing Method (rate)" and the headline "Routing Calls Skipping
> LLM (%)" stat — over `agent_supervisor_routes_total` (per-agent LLM cost
> panel already existed). Only **D** (Agent C SQL pushdown) remains, and it needs
> a live DB + settlement-locking care.

> **A + B landed.** Admin router: `GET/PUT /api/v1/intelligence/admin/agent-tuning[/{section}]`
> and `GET/PUT /admin/tax-rates[/{rate_key}]`, all guarded by `RequireUserManage`,
> delegating to the validated `db_tuning` service functions (bad override → 422,
> unknown section → 404). New schemas added; `frontend/.../schema.d.ts` regenerated
> (OpenAPI gate satisfied). B: `tests/integration/{test_db_tuning_integration,
> test_admin_tuning_api}.py` with a `tuning_tables` fixture that creates the two
> finguard-schema tables on the test DB; they cover the effective-dated SQL date
> filter, the agent_config write + validation, and the RBAC/404/422 matrix. These
> run in CI (need Postgres); verified locally by lint, type-check, router
> registration, OpenAPI generation, and collection. Remaining follow-up: a
> `DELETE /admin/agent-tuning/{section}` endpoint (not built).

**Recommended order:** B → A → C → E → D. B unblocks trustworthy testing of the
Sprint-1 DB layer; A builds on it; C and E are quick, isolated wins; D is the
big, risky one and should go last with the test scaffolding (B) already in place.

---

## A. Admin router for `agent_config` + `tax_rate_schedule`

**Goal:** expose the existing `db_tuning.upsert_agent_config()` /
`db_tuning.set_tax_rate()` service functions over HTTP so operators retune agents
and set effective-dated tax rates without DB terminal access.

**Approach — copy the established admin pattern** (`routers/admin.py`):
- Add endpoints to a new `routers/admin_tuning.py` (or extend `admin.py`):
  - `GET  /admin/agent-tuning` → current merged `get_agent_tuning()` (redacts nothing; read-only view).
  - `PUT  /admin/agent-tuning/{section}` → body = partial override dict → `upsert_agent_config(session, section, payload, updated_by=current_user.id)`.
  - `DELETE /admin/agent-tuning/{section}` → remove the row + `refresh_agent_tuning_from_db(force=True)`.
  - `PUT  /admin/tax-rates/{rate_key}` → body `{rate, effective_from, note}` → `set_tax_rate(...)`.
  - `GET  /admin/tax-rates` → list schedule rows.
- Guard every mutating route with `RequireUserManage` (ADMIN/OWNER), exactly like
  `ingest_knowledge_base`. Use `DBSession = Annotated[AsyncSession, Depends(get_db)]`.
- Aggregate the sub-router in `routers/router.py`.
- Add Pydantic request/response models to `schemas.py` (`AgentTuningUpdate`,
  `TaxRateUpdate`, `AgentTuningView`). **These are referenced by endpoints, so
  they *will* appear in `components.schemas`** — regenerate `schema.d.ts`.

**Gotchas (from `AGENTS.md`):**
- CSRF is auto-applied to the new mutating routes (double-submit middleware) — no action needed, but the frontend client must send the token.
- The **OpenAPI sync-types gate** will fail CI until you regenerate `frontend/src/lib/api/generated/schema.d.ts` (§5.1 recipe).
- `upsert_agent_config` already validates + rejects bad sections (raises `ValueError`); map that to `HTTP 422` in the handler.

**Testing:** an integration test (needs DB, see B) that `PUT`s an override, then
asserts a follow-up agent call reflects it; an RBAC test that a non-admin gets 403
(mirror the existing IDOR/RBAC tests).

---

## B. DB-integration tests for the Sprint-1 DB layer

**Goal:** cover the two things the hermetic tests can't — the `agent_config`
round-trip through the overlay, and the effective-dated `WHERE effective_from <= as_of`
SQL selection (the fake-session unit test only exercises the Python side).

**Approach — reuse the async DB test harness** (`tests/domains/finance/test_invoices.py`
is the template; CI already runs a `postgres` service, see `.github/workflows/ci.yml`):
- New `tests/domains/intelligence/test_db_tuning_integration.py`. These are
  **async** tests, so they automatically pull the session-scoped `create_tables`
  fixture (do **not** add the no-op override that the hermetic dir uses).
- Cases:
  1. `upsert_agent_config(session, "reconciler", {"txn_batch": 7})` → `refresh_agent_tuning_from_db(force=True)` → `get_reconciler_tuning().txn_batch == 7`; then env override still wins (precedence).
  2. Insert two `tax_rate_schedule` rows (2023 vat 0.14, 2024 vat 0.16) → `get_effective_auditor_tuning(session, date(2023,6,1)).vat_rate == 0.14` (the **SQL** date filter, not the Python one).
  3. Invalid `upsert_agent_config` payload raises `ValueError` and writes no row.
- Reset global state between tests: `clear_db_overlay()` + `reset` the TTL clock
  (expose a small `_reset_refresh_clock()` test hook in `db_tuning.py`, or call
  `refresh_agent_tuning_from_db(force=True)`).

**Gotchas:** `refresh_agent_tuning_from_db` is TTL-gated (60 s) and process-global —
always call with `force=True` in tests and clear the overlay in a fixture so state
doesn't leak across tests.

**Effort:** S once the fixture wiring is understood; it's the highest-leverage
deferred item because it makes the rest of the DB work trustworthy.

---

## C. Receipt scanner → single vision call (S3-3)

**Goal:** collapse the receipt pipeline's two LLM calls (vision OCR, then a
text classify) into one, halving latency/cost per scan.

**Key insight:** `tools/vision_ocr.extract_receipt` **already** uses
`response_schema=ReceiptExtraction`. Categorisation is a *field*, not a separate
model call.

**Approach:**
1. Add `suggested_category: str = "other"` to `ReceiptExtraction` (`schemas.py`),
   documented as one of `receipt_scanner.RECEIPT_CATEGORIES`.
2. Extend the vision prompt in `extract_receipt` to also choose the best category
   from that fixed list (same 5-value taxonomy).
3. In `agents/receipt_scanner.py`: keep `receipt_ocr_node`, and either (a) delete
   `receipt_classifier_node` and read `suggested_category` straight off the
   extraction, or (b) reduce the classifier node to a pure guard (`value in
   RECEIPT_CATEGORIES else "other"`) with **no** LLM call.
4. `orchestrator.build_receipt_graph`: topology becomes `START → receipt_ocr → END`.
5. Preserve the **human-in-the-loop fallback** — on OCR failure still return an
   empty `ReceiptExtraction` with `suggested_category="other"` so the form renders.

**Testing (hermetic, mock the vision client):** assert one `generate_*` call;
assert an out-of-taxonomy category from the model is coerced to `"other"`; assert
the degraded path still yields a fillable form. The existing
`test_agent_advisor`/composite mocks show the pattern.

**Gotcha:** if any frontend/consumer reads `suggested_category` from the old
classifier node's `context["suggested_category"]`, keep writing that key too (set
it from the extraction) so nothing downstream breaks.

---

## D. Agent C — SQL candidate pushdown + indexes (S3-4, the hard one)

**Goal (your guidance):** compute the amount/date candidate pre-filter in
PostgreSQL over indexes instead of materialising/looping in Python.

**Why it's risky:** `run_reconciliation` locks the invoice set up front with
`FOR UPDATE SKIP LOCKED` so two concurrent reconciler passes can't double-match
the same invoice, and settlement (`FinanceService.apply_reconciled_payment`) holds
each invoice `FOR UPDATE` while it re-projects the balance. Any rewrite must
preserve both. This is money-path concurrency — it needs a real DB to test.

**Recommended approach — SQL narrows, Python decides, locking unchanged:**
1. **Add indexes** (own migration, `CREATE INDEX IF NOT EXISTS`, verify column/enum
   names first against a live DB):
   - `mpesa_transactions (is_reconciled, created_at)`
   - `invoices (status, balance_due)` (or a partial index `WHERE balance_due > 0`)
   - `bank_statement_lines (is_reconciled, review_status, date)`
2. **Pass 1 as a candidate CTE**: replace the Python nested loop with a join that
   returns only (txn_id, invoice_id) pairs within amount tolerance + date window:
   ```sql
   SELECT t.id AS txn_id, i.id AS inv_id
   FROM mpesa_transactions t
   JOIN invoices i
     ON i.status IN ('SENT','OVERDUE') AND i.balance_due > 0
    AND abs(t.amount - i.balance_due) <= :tol
    AND (i.due_date IS NULL OR abs(EXTRACT(EPOCH FROM (t.created_at - i.due_date))/86400) <= :win)
   WHERE t.is_reconciled = FALSE
   ```
   Python then applies the **ref-substring** filter (`_ref_match`) and first-match
   dedup over this already-small candidate set.
3. **Keep locking where it is:** the settlement path (`apply_reconciled_payment`)
   already takes the per-invoice `FOR UPDATE`; keep the up-front
   `FOR UPDATE SKIP LOCKED` on the *transaction* batch. Decide deliberately whether
   to still lock the invoice set — simplest safe option is to keep loading + locking
   the invoice set for **Pass 2** (fuzzy needs the full set anyway), and let the
   Pass-1 CTE be a read that feeds the same settlement-with-lock.
4. **Pass 2 is unchanged** — rapidfuzz needs the full invoice set; SQL amount
   bucketing doesn't help it.

**Alternative if the CTE proves too entangled with locking:** keep the (already
shipped, tested) in-memory amount bucketing and *only* add the indexes — you get
most of the DB-efficiency win with none of the locking risk.

**Testing (must be integration, needs Postgres):** seed invoices + M-Pesa txns,
run `run_reconciliation`, assert the same matches as the current implementation;
add a concurrency test (two overlapping runs) asserting no invoice is double-settled.
The bucketing equivalence unit test (`test_reconciler_pass1_bucketing.py`) becomes
the oracle for the SQL version's expected output.

**Effort:** L. Do it behind the existing `run_reconciliation` signature so the
Celery task and node call sites are untouched.

---

## E. Grafana dashboard panels (S3-6)

**Goal:** make the Sprint-3 routing-cost win and per-agent LLM spend visible.

**Approach — extend the existing dashboard** (`monitoring/dashboards/finguard_ai_overview.json`;
it already has 9 panels with PromQL `expr`s over `agent_llm_processing_seconds`,
`agent_llm_tokens_total`, etc.):
- **Routing method breakdown** (stacked): `sum by (method) (rate(agent_supervisor_routes_total[5m]))`.
- **% routing calls that skipped the LLM** (stat/gauge — the headline Sprint-3 number):
  ```promql
  sum(rate(agent_supervisor_routes_total{method!="llm"}[5m]))
    / sum(rate(agent_supervisor_routes_total[5m]))
  ```
- **Per-agent LLM cost/hr**: `sum by (agent_id) (rate(agent_llm_cost_usd_total[5m])) * 3600`
  (the `AGENT_LLM_COST_USD` counter already exists).
- Add a matching panel to `infrastructure/grafana` provisioning if dashboards are
  provisioned from there too.

**Testing:** none automated — validate by importing the JSON into a local Grafana
(`make up` brings up the monitoring stack) and confirming the panels render with
live metrics after driving a few agent requests.

**Effort:** S. Pure JSON + PromQL; no app code.

---

## Cross-cutting notes

- **Verification environment:** items B and D genuinely need Postgres. The local
  `.venv` is broken (root-owned) — run tests via the uv-managed 3.12.13 interpreter
  (see the toolchain memo). CI already provisions Postgres, so these tests will run
  there even if local infra is down.
- **No new cross-domain imports:** keep tuning/registry/db_tuning within
  `intelligence` + `core` + `infrastructure` to satisfy the architecture boundary test.
- **After A:** run the OpenAPI sync-types gate and commit the regenerated
  `schema.d.ts`, or CI fails.
