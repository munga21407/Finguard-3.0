# Finguard 3.0 — Agent Remediation Sprint Plan

*Companion to [`AGENTS_REPORT.md`](./AGENTS_REPORT.md). Every con identified in that
report is triaged below into six themed, sequenced sprints. Each ticket traces back
to the agent(s) it fixes and carries acceptance criteria + a rough estimate.*

**Assumptions:** 2-week sprints, 1–2 engineers. Estimates are relative
(S ≈ ≤1 day, M ≈ 2–3 days, L ≈ 4–5 days). Reorder freely — the sequencing below
is by *leverage × dependency*, not hard requirement.

---

## Triage summary — every con mapped to a sprint

| # | Con (from report) | Agent(s) | Sprint |
|---|---|---|---|
| 1 | Tax rates/thresholds hard-coded | F | S1 |
| 2 | HMM emission/transition priors hard-coded | E | S1 |
| 3 | Bankability scoring weights/tiers hard-coded & unvalidated | G | S1 |
| 4 | Match thresholds (65/0.60/0.90) magic numbers | C | S1 |
| 5 | hub_writer `if`-chain implicit coupling | hub_writer | S2 |
| 6 | J hard-coded key allowlists | J | S2 |
| 7 | One insight artifact per pass (first match wins) | hub_writer | S2 |
| 8 | Supervisor calls the LLM every hop (cost/latency) | Supervisor | S3 |
| 9 | D fires up to 4 LLM calls (CoVe) | D | S3 |
| 10 | Receipt scanner = 2 sequential LLM calls | Receipt | S3 |
| 11 | C: O(txn × invoice) matching, 50-candidate cap | C | S3 |
| 12 | Heavy inline deps / import cost (statsmodels, reportlab, pandas) | D, E, G | S3 |
| 13 | No confidence gating on A's OCR fast-path | A | S4 |
| 14 | No eval/back-test for classification, HMM, bankability | B, E, G | S4 |
| 15 | On-the-fly fit = silent accuracy degradation for new customers | E | S4 |
| 16 | Self-grading verification (LLM checks LLM) | D, F | S4 |
| 17 | B: zero-shot, no feedback loop from user corrections | B | S5 |
| 18 | B: fixed 50-row batch can't drain large backlogs | B | S5 |
| 19 | Thin upstream context → generic advice | H | S5 |
| 20 | J bullet format brittle; translation unverified | J | S5 |
| 21 | Metropol & KRA are stubs (manual/unavailable) | I | S6 |
| 22 | Sandbox M-Pesa balance probe ≠ real transaction feed | I | S6 |
| 23 | Actionable-tier advice = advice-quality/liability risk | H | S6 |
| 24 | Supervisor cycle only stops at recursion ceiling (508) | Supervisor | S6 |
| 25 | OCR accuracy is the ceiling; tiny category set | A, Receipt | S6 |
| — | Single-jurisdiction (Kenya only) | F, G | Backlog (see §7) |

*Sprint 7 (tool-capability registry, VC-signed proposal decisions) isn't in this
table — it doesn't trace back to a con here; see the Sprint 7 section below for
its own provenance.*

---

## Sprint 1 — Externalize domain constants  *(highest leverage)*

> **Status: DONE (env + DB layers).**
> - **Env/default layer:** `src/domains/intelligence/tuning.py` holds all four
>   tuning groups; defaults reproduce the old hard-coded values. Override via
>   `AGENT_TUNING_JSON`; `validate_agent_tuning()` hard-fails in prod / warns in dev.
> - **Runtime DB layer:** `src/domains/intelligence/db_tuning.py` +
>   migration `0015` (`finguard.agent_config`, `finguard.tax_rate_schedule`).
>   `refresh_agent_tuning_from_db()` (TTL-gated, own session) installs an overlay;
>   section precedence is **env > DB > default**. Agents F/E/C/G refresh at node
>   entry (E/C rebind module globals, G/F read per-call) so an operator retunes
>   without a restart. `upsert_agent_config()` / `set_tax_rate()` are the admin writes.
> - **Effective-dated tax:** `get_effective_auditor_tuning(session, as_of)` picks the
>   latest `tax_rate_schedule` row ≤ the audit date; Agent F honours `ctx["as_of_date"]`.
> - **Tests:** `test_agent_tuning.py` + `test_db_tuning.py` (24 hermetic tests:
>   defaults==legacy, env>DB>default precedence, validation, effective-tax selection).
>   Full intelligence suite 182 passed (1 pre-existing Redis-dependent fail).
> **Remaining follow-up:** an operator-facing HTTP endpoint over
> `upsert_agent_config` / `set_tax_rate` (service functions exist; no router yet).

**Goal:** Nothing that a business analyst might change should require a code deploy.
Move baked-in financial/statistical constants into config (env + DB) with validation.

**Why first:** Touches the single most-repeated weakness, unblocks Sprint 4
(you can't tune what you can't configure), and is low-risk/mechanical.

| Ticket | Detail | Agent | Est |
|---|---|---|---|
| S1-1 | Introduce a typed `AgentTuning` settings block (Pydantic) + a `agent_config` DB table for values that change without deploy. Loader with env → DB → default precedence. | infra | M |
| S1-2 | Move VAT rate/threshold, CIT rate, TOT band, AML threshold out of `f_auditor.py` into config; add effective-dated rows so historical audits use period-correct rates. | F | M |
| S1-3 | Move HMM `EMISSION_PARAMS`, `TRANSITION`, `INITIAL_PI`, `DUPLICATE_THRESHOLD` into config; document each prior's meaning. | E | M |
| S1-4 | Move bankability sub-score weights + tier cutoffs (75/45) into config. | G | S |
| S1-5 | Move reconciliation thresholds (fuzzy 65, semantic 0.60, fuzzy/semantic 0.90, amount/date tolerances) into config. | C | S |
| S1-6 | Config-validation guard (fail-in-prod, warn-in-dev) mirroring `config.py::_validate_production`; unit tests asserting defaults equal today's hard-coded values (no behavior change). | infra | S |

**Acceptance:** All listed constants read from config; default run is byte-identical to
current behavior; changing a value requires no redeploy; validator rejects nonsense
(e.g. negative rates, tier cutoffs out of order).

---

## Sprint 2 — Decouple the persistence/summary layer

> **Status: DONE.** `src/domains/intelligence/agent_registry.py` is the single
> source of truth: one `AgentDescriptor` per output (agent_id, context_key,
> intent, ttl, priority, summary_order, optional payload_builder). `hub_writer`
> iterates `resolve_artifacts()` and now **persists every present artifact** per
> pass (was: first-match only) — also fixed a latent bug where Agent B's list
> payload silently failed the `dict`-typed `InsightArtifact.payload`. Agent J
> reads `executive_summary_keys()` at call time. Contract test
> (`test_agent_hub_writer.py`) proves a new agent surfaces in hub + J from one
> registry entry with zero edits to either module. 33 unit tests + full suite
> 185 passed (1 pre-existing Redis fail).
> - **Addendum (DeepSeek-harness-inspired hardening, later):** extended the same
>   decoupling philosophy to `hub_writer_node`'s own *internal* behavior — it was
>   still one monolithic function body (message compaction, GenUI persistence,
>   insight persistence all inline). Split into independent `HubWriterStep`
>   functions run against a shared read-only `_StepContext`, registered in an
>   ordered `HUB_WRITER_STEPS` list — a new cross-cutting concern (e.g. the
>   compaction step below) attaches as one more registry entry, matching S2's
>   "one entry, zero edits elsewhere" contract but applied to hub_writer's own
>   logic rather than just the agent↔hub_writer mapping. Also added a message
>   **compaction** step: `state["messages"]` is append-only with no built-in
>   limit (a gap this sprint's original scope didn't cover); past a threshold,
>   redundant repeat-visits from the same agent are pruned via LangGraph's
>   `RemoveMessage`, keeping every `HumanMessage` and the most-recent message
>   per agent name so the cycle guard's stall-detection can't be affected.
>   Tests: `test_agent_hub_writer.py` (+7: 2 registry-extension tests, 5
>   compaction tests) + `test_message_reconstructibility_invariant.py` (2 —
>   proves a pruned message is still recoverable from LangGraph checkpoint
>   history, and documents that this depends on checkpointing being enabled).

**Goal:** Adding a new agent should be *one* declarative registration, not edits
across `hub_writer`, its TTL maps, and Agent J's key lists.

**Why second:** Removes the structural coupling that makes every other agent change
more expensive; small, self-contained, high maintainability payoff.

| Ticket | Detail | Agent | Est |
|---|---|---|---|
| S2-1 | Define an `AGENT_REGISTRY`: `{context_key → AgentDescriptor(agent_id, intent, ttl, summary_order)}`. Single source of truth. | infra | M |
| S2-2 | Replace `hub_writer._extract_payload_and_intent` `if`-chain + `_AGENT_TTL_*` maps with registry lookups. | hub_writer | M |
| S2-3 | Replace Agent J's `_AGENT_OUTPUT_KEYS` / `_SKIP_KEYS` with registry-derived lists (summary keys = registry keys; skip = everything else). | J | S |
| S2-4 | Allow hub_writer to persist **all** recognized artifacts in a pass, not just the first match (iterate registry, upsert each present key). | hub_writer | M |
| S2-5 | Contract test: registering a dummy agent key surfaces it in hub + J with zero edits to hub_writer/J source. | test | S |

**Acceptance:** A new agent is added by one registry entry; hub_writer/J source
untouched; multi-agent sessions persist every produced artifact; existing tests green.

---

## Sprint 3 — Cost & performance

> **Status: mostly DONE.**
> - **S3-1 (supervisor):** deterministic keyword router + bounded initial-decision
>   cache + single-agent FINISH short-circuit → clear single-agent intents cost
>   **0 LLM routing calls**. New `agent_supervisor_routes_total{method}` metric
>   sizes the win. (`supervisor.py`, tests in `test_supervisor_router.py`.)
> - **S3-2 (Agent D CoVe):** Drafter+Explainer folded into one call → verified
>   path is **2 LLM calls (was 3)**; `ctx["cove_verify"]=false` drops it to 1.
>   (`test_agent_forecaster_cove.py`.)
> - **S3-4 (Agent C):** Pass 1 amount-bucketing removes the O(txn×invoice) scan
>   (proven equal to brute force in `test_reconciler_pass1_bucketing.py`); the LLM
>   candidate cap now configurable (`ReconcilerTuning.pass2_candidate_cap`).
> - **S3-5:** sklearn now lazily imported in `e_watchdog` + `model_store`
>   (statsmodels/reportlab/pandas were already deferred).
> - **Deferred (need a live DB):** the full **SQL-join candidate pushdown** for
>   Agent C + its supporting indexes (documented in `c_reconciler` docstring) —
>   changes settlement locking, so it needs integration testing. **S3-6** Grafana
>   dashboards: the `agent_supervisor_routes_total` + existing per-agent cost
>   metrics are emitted; the dashboard JSON itself is unbuilt.
> Full suite: 199 passed (1 pre-existing Redis fail).
> - **Addendum (DeepSeek-harness-inspired hardening, later):** S3-1's keyword
>   router only ever cut the supervisor's *LLM call* — the graph still paid a
>   full `supervisor → agent → hub_writer → supervisor → END` round-trip even
>   for a zero-LLM-call route. `orchestrator.try_fast_path` now skips the
>   **graph traversal itself** for a clean single-agent match on a `read_only`
>   agent (D, F): `build_fast_path_graph(node_name)` runs `START → agent →
>   hub_writer → END` directly, reusing the exact same keyword table
>   (`agent_registry.heuristic_route`, extracted from `supervisor.py` so both
>   paths share one classifier) gated by a new `AgentDescriptor.read_only`
>   flag so a write-capable agent (K) never gets fast-pathed even on a clean
>   match. Wired into all three call sites that build a graph
>   (`service.py`, `routers/_common.py`, `routers/conversations.py`).
>   Tests: `test_orchestrator_fast_path.py` (7 tests). Intelligence suite
>   after this addendum + Sprint 2's hub_writer/compaction addendum: 341
>   passed (1 pre-existing Redis fail).

**Goal:** Cut per-session LLM spend/latency and remove the algorithmic/dependency hot spots.

**Why third:** Directly hits run-cost and user-perceived latency; depends on S1 (thresholds
now configurable) for the routing/heuristic tuning knobs.

| Ticket | Detail | Agent | Est |
|---|---|---|---|
| S3-1 | Supervisor: short-circuit common single-agent intents with a deterministic keyword/heuristic router before falling back to the LLM; cache routing decisions per intent signature. Measure LLM-call reduction. | Supervisor | L |
| S3-2 | Agent D: collapse CoVe from 3 calls to 1–2 (combined draft+explain, or skip explainer when draft confidence high); make CoVe opt-in per request. | D | M |
| S3-3 | Receipt scanner: fold OCR + categorization into a single structured-output vision call (category as a field in `ReceiptExtraction`). | Receipt | M |
| S3-4 | Agent C: index/pre-bucket invoices by amount band + date window to avoid the full O(txn × invoice) scan; make the 50-candidate LLM cap configurable and page residuals across runs. | C | L |
| S3-5 | Confirm/standardize lazy imports for statsmodels, reportlab, pandas/openpyxl, sklearn so agents that don't use them pay no import cost; add a startup-time assertion. | D, E, G | S |
| S3-6 | Add per-session LLM-call-count + cost dashboards (build on `_tracked` metrics) to verify the reductions land. | infra | S |

**Acceptance:** Median supervisor LLM calls/session down measurably (target ≥30% on
single-agent intents); D default path ≤2 LLM calls; receipt scan = 1 call; C matching
benchmarked faster at 10× volume; no regression in output quality on the eval suite.

---

## Sprint 4 — Model quality, validation & honesty

> **Status: DONE.**
> - **S4-1 (B):** immutable `CLASSIFICATION_CASES` in `datasets.py` + nightly
>   accuracy judge (`test_agent_b_classification_judge.py`, llm-gated) + hermetic
>   coverage/taxonomy guard tests (`test_sprint4_guards.py`).
> - **S4-2 (E):** deterministic HMM/IsolationForest eval over immutable labeled
>   series (`test_agent_e_anomaly_eval.py`) — blocks CI, no LLM/DB.
> - **S4-3 (G):** bankability calibration over healthy/moderate/distressed
>   profiles (`test_agent_g_bankability_eval.py`) — tier + monotonic-ordering asserts.
> - **S4-4 (A):** OCR fast-path now gated by a confidence floor (0.6) — low-confidence
>   reads fall through to the LLM instead of being accepted.
> - **S4-5 (E):** `WatchdogAnalysis` + `BudgetWatchdogMeter` now expose
>   `isolation_model` (`persisted`/`on_the_fly`) + `degraded` so degraded runs are visible.
> - **S4-6 (D/F):** deterministic gates independent of the LLM — D rejects any
>   non-SELECT draft regardless of the audit verdict; F's AML + VAT-registration
>   flags are machine-injected via `_inject_deterministic_flags`.
> - **Regression fix:** the Sprint-1 tax-constant externalisation had **broken**
>   `test_agent_f_tax_evals.py` / `test_agent_f_narrative_judge.py` (they imported
>   removed `_VAT_RATE` etc. and the old `_calculate_tax_liability` signature) —
>   now fixed to use `AuditorTuning`. Added `tests/evals/conftest.py` so the
>   deterministic evals run without Postgres. Evals: 43 passed / 3 nightly-skipped;
>   intelligence suite 208 passed. `schema.d.ts` regenerated (ReceiptExtraction).
> - **Addendum (DeepSeek-harness-inspired hardening, later):** S4-6's
>   "self-grading isn't the only gate" pattern (LLM verdict + a deterministic
>   override) extended to a third agent that didn't exist when this sprint was
>   scoped — **Agent K**. `_cove_verify_stock_action` audits a proposed stock
>   adjustment against the same inventory evidence K already gathered, mirroring
>   D's CoVe shape but as a pure verifier (K's action is deterministic caller
>   input, not model output, so there's nothing to draft). Unlike D's audit
>   (which gates whether the SQL executes), K's write already requires human
>   approval either way — an unsupported verdict is folded into the proposal's
>   `rationale` as a flag rather than blocking, so the human reviewer sees it
>   before deciding. Toggle: `k_cove_verify` context flag, same convention as
>   D's `cove_verify`. Tests: `test_agent_k_stockkeeper_cove.py` (6 tests,
>   including the deterministic-gate-overrides-a-passing-LLM-verdict case).

**Goal:** Know when an agent is right, and never silently serve a degraded result.

**Why fourth:** Requires S1 (configurable params to tune against evals). Builds the
back-tests the tuned constants should be validated on.

| Ticket | Detail | Agent | Est |
|---|---|---|---|
| S4-1 | Eval harness for Agent B classification (labeled fixture set, accuracy/precision by category), mirroring existing Agent F evals. | B | M |
| S4-2 | Eval/back-test for Agent E: HMM state decoding + IsolationForest on synthetic labeled anomaly series; assert detection rate/false-positive bounds. | E | L |
| S4-3 | Calibration test for Agent G bankability score against a labeled outcome set (or a documented synthetic proxy until real default data exists). | G | M |
| S4-4 | Agent A: add confidence gating to the OCR fast-path — below a configurable threshold, fall through to LLM text extraction instead of accepting the OCR dict. | A | S |
| S4-5 | Agent E: surface `model_used` / on-the-fly-fit-degradation flag in the output payload + `BudgetWatchdogMeter` widget so users see when results are degraded. | E | S |
| S4-6 | Harden self-grading (D CoVe auditor, F compliance): add deterministic post-checks (schema/row-sanity for D's SQL results; numeric cross-check for F's flags) so the LLM verdict isn't the only gate. | D, F | M |

**Acceptance:** CI runs B/E/G evals with committed baselines; A fast-path rejects
low-confidence OCR; degraded E runs are visibly flagged end-to-end; D/F have at least
one non-LLM verification check.

---

## Sprint 5 — Feedback loops & output robustness

> **Status: DONE.**
> - **S5-1:** `finguard.classification_feedback` table (mig `0017`) +
>   `classification_feedback_service` to record corrections with a 768-dim embedding.
> - **S5-2:** vector-similarity retrieval of nearest past corrections injected as
>   few-shot into Agent B's prompt (`get_fewshot_examples` → `format_fewshot_block`);
>   degrades to zero-shot on any miss. Per the saved guidance (relevance, not recency).
> - **S5-3:** Agent B batch size is now `ClassifierTuning` (env/DB-overridable, in the
>   admin API); `_fetch_unclassified_entries` takes a runtime limit.
> - **S5-4:** Agent H computes upstream `data_completeness` (full/partial/none); with
>   none it prepends a hard "⚠️ Limited data" disclaimer instead of confident guidance.
> - **S5-5:** Agent J emits **structured** `ExecutiveSummary` bullets (no more
>   `•`/`**` string parsing); count/labels come from the structure; rendered string
>   kept for back-compat + new `executive_summary_bullets`.
> - **S5-6:** Agent J verifies numeric tokens survive translation
>   (`_translation_preserves_numbers`) and falls back to the English source on loss.
> - Tests: `test_sprint5.py` (10) + updated advisor test. Suite 261 passed / 3
>   nightly-skipped. `schema.d.ts` regenerated (AgentTuningView + classifier).
> **Follow-up:** an HTTP endpoint to *capture* corrections into the feedback table
> (the `record_feedback` service exists; no router yet).

**Goal:** Let the system learn from users and make derivative agents (H, J) resilient.

| Ticket | Detail | Agent | Est |
|---|---|---|---|
| S5-1 | Capture user corrections to Agent B classifications (accept/override events) into a `classification_feedback` table. | B | M |
| S5-2 | Feed accumulated corrections back as few-shot examples in the classifier prompt (retrieval of nearest labeled examples per batch). | B | L |
| S5-3 | Agent B: make batch size configurable + add a drain-loop mode so large backlogs clear across a scheduled run instead of one 50-row pass. | B | S |
| S5-4 | Agent H: detect thin upstream context (few/no populated agent outputs) and either request the missing agents run first or clearly label the advice as "limited data". | H | M |
| S5-5 | Agent J: replace brittle bold-bullet parsing with structured output (list of `{label, text}`) rendered to markdown client-side; count/label bullets from the structure, not string `.count("•")`. | J | M |
| S5-6 | Agent J: add a lightweight translation-fidelity check (e.g. verify KES figures/numerals survive translation) before returning localized bullets. | J | S |

**Acceptance:** Corrections persist and measurably improve B accuracy on the S4-1 eval;
B drains a >50 backlog; H degrades honestly on thin context; J output is structured and
locale output preserves all numerals.

---

## Sprint 6 — Integration completion & safety guardrails

> **Status: code-complete for the non-vendor-gated tickets (S6-3, S6-4, S6-5, S6-6);
> S6-1 / S6-2 remain blocked on commercial credentials (code paths already exist).**
> - **S6-3 (M-Pesa real feed):** Agent I now prefers the real
>   `mpesa_transactions` ledger (ingested via the C2B/STK callback) over the
>   sandbox AccountBalance probe — `_fetch_mpesa_ledger()` returns a `live`
>   callback feed (recent txns + credit total) when rows exist, else falls back
>   to the probe (dev mock / prod `unavailable`). Never fabricates. Going fully
>   live still needs prod Daraja creds + the callback receiving real traffic.
> - **S6-4 (supervisor cycle detection):** a benign loop (same `next`, no new
>   agent output / context) now terminates *gracefully* at FINISH with a
>   degraded reason (`agent_supervisor_routes_total{method="cycle_break"}`)
>   before the LangGraph recursion ceiling. Keys off a `_progress_signature`
>   (distinct agents + public context keys), not a raw counter, so a context
>   overwrite can't hide a stall. (`supervisor.py`, `test_supervisor_cycle_guard.py`.)
> - **S6-5 (Agent H guardrails):** actionable-tier advice carries a standing
>   advice-liability disclaimer (appended deterministically) and, when the
>   human-review gate is on (`settings.AGENT_H_REVIEW_GATE` or
>   `context["require_advice_review"]`), is flagged `requires_review` /
>   `review_status="pending_review"` with a hold notice. Summary tier is
>   unaffected. (`h_advisor.py`, `test_agent_advisor.py`.)
> - **S6-6 (OCR ceiling):** low-confidence receipt scans (< `receipt.ocr_min_confidence`)
>   are re-run once with a higher-fidelity vision model (`VISION_RETRY_MODEL`);
>   the more confident read wins, retry failures keep the first read. The receipt
>   taxonomy is now a config section (`ReceiptTuning.categories`) so operators can
>   extend it without a deploy; the schema clamp reads the effective set. The
>   `model` override is threaded through the vision LLM path. (`vision_ocr.py`,
>   `tuning.py`, `schemas.py`, `test_receipt_multipass.py`.)
> - **Config:** added `VISION_RETRY_MODEL`, `AGENT_H_REVIEW_GATE`; new
>   `receipt` tuning section (env/DB-overridable, in the admin `AgentTuningView`).
>   `schema.d.ts` regenerated (AgentTuningView.receipt).
> - Tests: 77 affected intelligence tests pass; ruff + mypy clean on changed files.
> **Remaining (vendor-gated):** S6-1 Metropol + S6-2 KRA live activation (both
> already have `live` code paths guarded by API-key presence — just need onboarding).

**Goal:** Turn the stubbed external sources live and close the remaining safety gaps.
Larger/vendor-dependent — schedule when commercial access is available.

| Ticket | Detail | Agent | Est |
|---|---|---|---|
| S6-1 | Integrate Metropol credit API for real (replace manual/unavailable path); keep the honest-provenance model. | I | L |
| S6-2 | Integrate KRA iTax VAT/compliance for real; same provenance guarantees. | I | L |
| S6-3 | Wire a real M-Pesa transaction feed (via the C2B/STK callback ingestion) into Agent I instead of the sandbox balance probe. | I | M |
| S6-4 | Supervisor: add lightweight cycle detection (e.g. repeated identical `next` with no new context) that routes to FINISH *before* the recursion ceiling, with a clear degraded-response reason. | Supervisor | M |
| S6-5 | Agent H actionable tier: add a disclaimer/guardrail layer + optional human-review gate for concrete financial recommendations (advice-liability mitigation). | H | M |
| S6-6 | Improve OCR ceiling: allow multi-pass / higher-fidelity vision model for low-confidence receipts; expand the receipt category set behind config (ties to S1). | A, Receipt | M |

**Acceptance:** Metropol/KRA/M-Pesa report `live` status with real data in prod;
supervisor escapes cycles gracefully (no 508 from a benign loop); actionable advice
carries a disclaimer + review path; low-confidence receipts get a second pass.

---

## Sprint 7 — DeepSeek-harness-inspired hardening

> **Status: DONE.** Unlike Sprints 1–6, these tickets don't trace back to a con
> in `AGENTS_REPORT.md` — they came from comparing Finguard's orchestrator
> against `deepseek-ai/deepseek-harness`'s plugin/capability-seam design and
> picking the ideas that addressed a real, already-felt gap (see addenda on
> Sprints 2–4 above for the routing/hub_writer/CoVe pieces of this same pass).
> This section covers the two tickets that don't extend an earlier sprint.

| Ticket | Detail | Status |
|---|---|---|
| S7-1 | Generalize `sql_executor.py`'s per-agent table allowlist (`_AGENT_ALLOWED_TABLES`) into a cross-tool registry (`agent_registry.TOOL_GRANTS` — SQL tables, HTTP hosts, RabbitMQ exchanges) and enforce it **per calling agent**, not a global union. | DONE |
| S7-2 | Extend the Ed25519 VC / `trust_log` audit trail (previously Agent E's watchdog only) to human proposal-approval decisions. | DONE |

**S7-1 detail — a real bug, not just tidiness:** `execute_readonly_sql()` enforced
the *union* of every agent's declared tables regardless of caller. Agent E calls
it twice and was never even listed in the allowlist dict, yet had de facto access
to all 7 tables across D's and K's grants — it just happened to only ever query
`ledger_entries`/`invoices`. `TOOL_GRANTS` closes this: `execute_readonly_sql`,
`get_masked_schema`, `make_http_caller`, and `make_event_publisher` all now take
the calling `agent_id` and scope to exactly its own grant. Zero behavior change
for any agent's *actual* queries/calls — every change is a tightening of a
previously-accidental over-grant. `inventory_tools`/`vision_ocr` were
deliberately left ungranted (mandatory HITL already covers the one write path;
no SQL/HTTP/events surface, respectively). `mongo_reader` was also left
ungranted at the time — that gap (zero callers *and* zero enforcement) was
closed in Sprint 8 below, before any agent adopted it.
Tests: `test_agent_registry_tool_grants.py` (7), `test_sql_executor_agent_scoping.py`
(6), 2 new cases in `test_http_caller_ssrf.py`, `test_event_publisher_scoping.py`
(4) — 19 new tests, full intelligence suite 362 passed (1 pre-existing Redis fail).

**S7-2 detail:** `ProposalService.approve()`/`reject()` now call `issue_vc()`
(the same function `e_watchdog.py` already used) after the Postgres decision is
durably committed — best-effort, never blocking or rolling back an
already-successful approval on a Mongo hiccup, mirroring E's existing
call-site pattern exactly. The plain `audit_logs` row (written by the router via
`AuditService`, unsigned) stays the system of record regardless; the VC is an
additional, tamper-evident copy. Tests: `test_proposal_vc_audit.py` (2 — signs on
success, never raises on `issue_vc` failure).

**Files:** `agent_registry.py`, `tools/sql_executor.py`, `tools/http_caller.py`,
`tools/event_publisher.py`, `proposal_service.py`, plus the call-site updates in
`d_forecaster.py`, `e_watchdog.py`, `i_integrator.py`. See `docs/A2A_PROTOCOL.md`
§4.6 for the design and `docs/AGENTS_REPORT.md` §3 for the cross-cutting strength
this adds.

---

## Sprint 8 — Write-policy hardening, planner adoption, agent decomposition

> **Status: DONE.** Like Sprint 7, these don't trace back to a con in
> `AGENTS_REPORT.md` — they came from an architectural review of the
> intelligence domain that surfaced seven gaps: an unenforced trust protocol,
> an inconsistent write policy (Agent C bypassed the HITL gate every other
> value-changing agent goes through), the A2A planner sitting unused, an
> ungranted `mongo_reader`, three ~600-line agent files mixing LangGraph
> plumbing with real business logic, no shared call path for Celery workers,
> and cost telemetry that silently reads zero. All eight are now closed or
> explicitly deferred with a stated reason.

| Ticket | Detail | Status |
|---|---|---|
| S8-1 | Bind `ProposalService.approve()`/`reject()` to an `expected_action_type`, closing a real cross-action-type authorization gap. | DONE |
| S8-2 | Payload-integrity check (`payload_hash`) at approval time, in place of task-scoped VC. | DONE |
| S8-3 | Migrate Agent C's Pass 2 (LLM-judged) reconciliation matches to `ProposalService`; Pass 1 (deterministic) unchanged. | DONE |
| S8-4 | Close the `mongo_reader` tool-grant gap (§4.6 of `A2A_PROTOCOL.md`). | DONE |
| S8-5 | Add planner `consumes` edges for Agent H; add the planner's first Prometheus metrics + two Grafana panels. | DONE |
| S8-6 | Split `c_reconciler.py` / `e_watchdog.py` / `g_reporter.py` into `services/*.py` (framework-agnostic) + thin LangGraph nodes. | DONE |
| S8-7 | `use_cases.py` — one implementation of the node+hub_writer call sequence, shared by the two Celery call sites that previously hand-assembled it. | DONE |
| S8-8 | Startup warning when the active LLM model has no cost-telemetry entry. | DONE |

**S8-1/S8-2 detail — the trust-protocol decision.** `security/vc_issuer.py`'s
task-scoped VC (`issue_task_scoped_vc`/`validate_task_vc`) has a hard 5-minute
TTL by design — issue-then-immediately-validate, right before a write. But
`ProposalService` exists precisely so a *human* can take minutes-to-days
between `create_proposal` and `approve`. Wiring the task-scoped VC into that
flow as originally scoped would have meant every proposal failed validation
the moment a reviewer took longer than 5 minutes — caught before writing any
code, not after. Also: since issuance and validation would both happen inside
the same trusted process either way, a self-issued-and-self-validated token
adds no protection against an external attacker today — it only proves the
same process can sign and check its own tokens. What the flow actually needs
is a *long-window integrity* guarantee, not a *short-window freshness* one, so
`AgentActionProposal` gained a `payload_hash` column (SHA-256,
`vc_issuer.payload_hash` — made public, was `_payload_hash`) set at
`create_proposal` and re-checked at `approve()` before the write replays.
`validate_task_vc`/
`issue_task_scoped_vc` remained test-only as of this sprint — the correct
outcome of using the right tool for the actual invariant here, not a leftover
gap; `approve()`/`reject()` still never touch them, unchanged by the later
"Task-scoped VC end-to-end" work below, which gave them a real caller on a
different class of write (live, in-process, audit/defense-in-depth) — not
because agent execution and write execution became separate trust domains
(they still aren't).
Migration `0026_agent_proposal_payload_hash.py`.

Separately, `approve()`/`reject()` now take a required `expected_action_type`
kwarg and reject a mismatch — found while wiring S8-3's second action type:
the original single-endpoint design had no structural check that a proposal's
`action_type` matched the endpoint that decided it, so a reviewer holding only
`finance:reconcile` could have approved a `stock.adjustment` proposal by
guessing its id. Each router endpoint now pins its own action type
(`routers/proposals.py`'s existing split-endpoint comment called this out in
advance of the second action type arriving).

**S8-3 detail — closing Agent C's HITL gap.** `run_reconciliation`/
`run_bank_reconciliation` applied every confirmed match — Pass 1 exact AND
Pass 2 LLM-judged (rapidfuzz + model-scored) — inline, with no human review,
unlike every other value-changing agent (K's stock adjustments already went
through `ProposalService`). Only Pass 2 is the actual risk (an LLM judgment
call moving real ledger state); Pass 1 still settles immediately — Agent C's
own docstring already established that `apply_reconciled_payment`'s
`FOR UPDATE` + balance-clamp is the real safety gate, so an unreviewed
*deterministic* match was never the concern. Pass 2 matches now land as
`AgentActionProposal(action_type="reconciliation.match")`, created **after**
Pass 1's `session.begin()` block commits (`ProposalService.create_proposal`
owns its own transaction and can't nest inside another), with an idempotency
guard so the same unresolved match isn't re-proposed every batch. New
`/proposals/reconciliation/{id}/approve|reject` endpoints, gated by
`finance:reconcile` (the same permission that already gates importing bank
statements). `ReconciliationReport` gained a `proposed_for_review` field so a
consumer doesn't have to infer from `matched_fuzzy` that "matched" no longer
means "settled."

**S8-6/S8-7 detail — decomposition, not a rewrite.**
`services/reconciliation_service.py`, `services/anomaly_service.py`,
`services/bankability_service.py` hold everything each agent computes;
`agents/c_reconciler.py`, `agents/e_watchdog.py`, `agents/g_reporter.py`
shrank to 53–117 lines each (from 669/608/579) and now only read
`OrchestratorState`,
call the service, and shape a GenUI payload. `e_watchdog`'s split preserves an
easy-to-miss original property: the Postgres session closes *before* the
slower DB-free work (HMM math, VC issuance, the LLM call, event publish) —
`fetch_watchdog_inputs` (session-scoped) and `run_watchdog_analysis`
(session-free) are two functions, not one, specifically to keep that
lifecycle intact. `use_cases.py` gives `watchdog_consumer.py` and
`reporting_tasks.py` one shared `run_watchdog_for_expense`/`run_monthly_report`
instead of each hand-building the node→merge→hub_writer sequence — `batch.py`'s
reconciliation tasks already delegated cleanly (nothing to consolidate there),
and its classification path deliberately keeps a separate implementation from
`agents.b_classifier` to avoid a circular import, so it's untouched.

Tests: 803 passed, 5 skipped, full backend suite (up from 794 at Sprint 7),
`ruff check` clean on every touched file. Verified against a throwaway
Postgres + Redis (not the project's shared dev stack) rather than assumed.

**Files:** `proposal_service.py`, `models.py` + migration `0026`,
`routers/proposals.py`, `agents/c_reconciler.py`, `agents/e_watchdog.py`,
`agents/g_reporter.py`, `services/reconciliation_service.py`,
`services/anomaly_service.py`, `services/bankability_service.py`,
`use_cases.py`, `workers/consumers/watchdog_consumer.py`,
`workers/tasks/reporting_tasks.py`, `agent_registry.py`,
`tools/mongo_reader.py`, `agents/planner.py`, `core/metrics.py`,
`llm/pricing.py`, `main.py`. See `docs/A2A_PROTOCOL.md` §4.6 for the
`mongo_reader` grant design.

---

## Sprint 9 — Round-2: closing the gaps a follow-up audit found in Sprint 8

> **Status: DONE.** A follow-up audit reviewed the Sprint 8 tree and found it
> solid but incomplete: `vc_issuer.py` still said agents "MUST" call
> `validate_task_vc()` (Sprint 8 replaced that flow with `payload_hash` but
> never updated the docstring saying so); there was no declarative record of
> *which* agents may mutate state *how* (B/E/K's ad hoc `mode == "actions"`
> checks had no registry-level backing, unlike the tool grants); and Agent D
> was the one fat node (~447 lines) the Sprint 8 decomposition pass hadn't
> reached. Every claim was independently re-verified against the code before
> planning the fix — one claim (doc staleness on the `consumes` surface) had
> already been fixed in the intervening "update the docs" pass and was
> confirmed stale-on-the-audit's-side, not stale-in-the-repo.

| Ticket | Detail | Status |
|---|---|---|
| S9-1 | Align `vc_issuer.py` / `agent_cards.py` docstrings with the `payload_hash` reality — no functional change. | DONE |
| S9-2 | Declarative, *enforced* mutation-capability matrix (`AgentDescriptor.mutations` / `mutation_kinds`) — same posture as `TOOL_GRANTS`. | DONE |
| S9-3 | Split `d_forecaster.py` into `services/forecast_service.py` + a thin node — the fourth agent split this way (C/E/G in Sprint 8). | DONE |
| S9-4 | Integration test exercising the planner through the *real* `orchestrator.build_graph()` (not a stub graph) with `A2A_PLANNER_ENABLED` flipped on. | DONE |

**S9-1 detail.** No code behavior changed — `issue_task_scoped_vc`/
`validate_task_vc`/`exchange_cards` were already unused (Sprint 8 confirmed
this), only their docstrings still described them as mandatory. Rewrote both
modules' docstrings to state plainly: not wired into any live path today;
`ProposalService`'s `payload_hash` check is what actually gates a write, and
why (5-minute TTL vs. a review queue spanning hours to days); these functions
remain the right primitive for a genuine agent-execution/write-execution
trust-domain split, which doesn't exist yet. (As of the later "Task-scoped VC
end-to-end" work below, `issue_task_scoped_vc`/`validate_task_vc` did get a
real caller — `require_task_vc`, on C/E/K/B's write paths — but for
audit/defense-in-depth, not because that trust-domain split happened; it
still hasn't. `exchange_cards` is unaffected either way — still uncalled, see
`agent_cards.py`'s own docstring for `verify_own_card`, its narrower
same-purpose sibling that did get wired in.)

**S9-2 detail — a real enforcement layer, not just documentation.** Added
`AgentDescriptor.mutations: frozenset[MutationKind]`
(`MutationKind = Literal["proposal", "event", "direct_write"]`) and
`agent_registry.mutation_kinds(agent_id)`, mirroring
`TOOL_GRANTS`'s fail-closed posture. Declares the verified status quo (no
behavior change): B `{"direct_write"}` (Celery-dispatched category persist,
no proposal — low blast-radius, metadata not money), C
`{"direct_write", "proposal"}` (Pass 1 / Pass 2), E `{"event", "direct_write"}`
(anomaly publish / background ML fit — never "proposal", E has no
financial/inventory write path), K `{"proposal"}`. Enforced at every actual
mutation call site: `event_publisher.make_event_publisher` (covers E's
RabbitMQ publish transitively, and any future agent that reuses it),
`b_classifier`'s Celery dispatch, `reconciliation_service`'s Pass 1 apply loop
(a `RuntimeError` guard, not a tool-string return — a background batch job
should fail loudly on a registry/code drift, not silently under-reconcile),
`anomaly_service`'s background-fit trigger, and `ProposalService.create_proposal`
(resolves `agent_label` → registry `agent_id` via the existing
`_ACTION_AGENT_ID` map before checking — proposals are keyed by a display
label, not the registry id, a distinction Sprint 8 already had to get right
for VC issuance). All additive; zero behavior change confirmed by the full
suite passing unchanged plus new grant tests.

**S9-3 detail.** Same pattern as C/E/G: `services/forecast_service.py` now
holds Holt-Winters fitting, the regime detector, runway estimation, and the
CoVe Text-to-SQL workflow, plus two orchestrating entry points —
`fetch_forecast_inputs` (session-scoped) and `compute_forecast` (session-free)
— so `agents/d_forecaster.py` (447 → 105 lines) only reads state, calls those
two functions, and shapes the GenUI payload. Caught and fixed a design bug
before it shipped: an early draft had the node call the low-level service
helpers (`_fetch_daily_cashflow`, `_fit_holtwinters`, etc.) directly, which
technically worked but silently broke test-mock patching (Python resolves a
bare name via the *importing* module's namespace, not the *defining*
module's) and would have made D the only one of the four splits with a
different, more fragile shape. The two-entrypoint design fixes both problems
at once.

**S9-4 detail.** `test_planner.py` already proves the planner's staging/
criticality/replan logic and its Send/join/loop wiring against a hand-built
stub graph; no test exercised `orchestrator.build_graph()` itself — the
actual function that decides whether `A2A_PLANNER_ENABLED` produces a
correctly-wired graph. New `test_planner_end_to_end.py` flips the flag,
stubs D/F/G/J's node factories and hub_writer at the `orchestrator` module
level (mirroring `test_orchestrator_fast_path.py`'s existing pattern), and
drives a multi-target board-pack intent through the real compiled graph,
asserting stage order, one hub_writer call per stage, and that the DAG
actually drains (`_planner_done`) rather than hitting the recursion ceiling.
Doesn't flip the flag anywhere real — that decision still needs staging
traffic data no one has generated yet — but means that decision, whenever
someone makes it, isn't the first time the real graph wiring gets exercised.

Tests: 811 passed, 5 skipped, full backend suite (up from 803 at the end of
Sprint 8), `ruff check` clean on every touched file.

**Files:** `security/vc_issuer.py`, `security/agent_cards.py`,
`agent_registry.py`, `tools/event_publisher.py`, `agents/b_classifier.py`,
`services/reconciliation_service.py`, `services/anomaly_service.py`,
`proposal_service.py`, `agents/d_forecaster.py`,
`services/forecast_service.py` (new).

**What S8/S9 deliberately left open** (so the next reader doesn't mistake
these for gaps still to close, or code-review them as accidents):

- **A2A planner ship-or-freeze.** `A2A_PLANNER_ENABLED` stays `False`.
  Flipping it needs staging traffic data and a deployment action — not
  something a sprint can resolve from inside the repo. S9-4's integration
  test only makes that decision safer to make later, whenever it's made; see
  §6 (Phased rollout) above.
- **`exchange_cards()`** — kept, not deleted (reaffirmed 2026-09-04; see
  "optional wave — item 7 revisit" below). Still uncalled and untested as of
  this writing — the right primitive if agent execution and write execution
  ever split into separate trust domains; revisit deletion only if that still
  hasn't happened in a few more sprints. Its narrower same-purpose sibling,
  `verify_own_card()` (one-party, not exchange_cards' two-party handoff), did
  get wired in and tested as part of the later "Task-scoped VC end-to-end"
  work below — that doesn't change this bullet's status for `exchange_cards`
  itself. **Task-scoped VCs** (`issue_task_scoped_vc`/`validate_task_vc`,
  wrapped by `require_task_vc`) were genuinely uncalled and test-only when
  this bullet was first written (2026-09-04); as of 2026-09-05 they have a
  real caller on Agent C/E/K/B's write paths for audit/defense-in-depth — see
  "Task-scoped VC end-to-end" below for the full reasoning. That still isn't
  the agent-execution/write-execution trust-domain split this bullet
  describes; it hasn't happened.
- **B and E's writes stay ungated by human review** — a risk-based choice via
  `AgentDescriptor.mutations` (S9-2), not an inconsistency to fix later. B
  mislabels a category (metadata, correctable); E publishes an alert or
  triggers an ML retrain (no direct financial/inventory effect). Neither is
  in the same risk class as C's Pass 2 or K's stock write-offs, which *are*
  proposal-gated. Reclassify a specific agent by editing its `mutations` set
  if that risk judgment changes. **Reaffirmed 2026-09-04** (item 8 of the
  optional wave, explicitly revisited): B's write is still a background
  Celery task persisting `ledger_entries.category` (metadata); E's are still
  a live RabbitMQ CRITICAL-state publish plus a weekly background per-customer
  IsolationForest retrain (notification + ML hygiene, not a financial/
  inventory action). Nothing about either write's blast radius has changed
  since S9-2 — no code change made.
- **C's Pass 1 (deterministic exact match) still auto-applies** — no LLM in
  the loop, and `FinanceService.apply_reconciled_payment`'s `FOR UPDATE` +
  balance-clamp is the actual safety gate (see the Agent C entry in
  `AGENTS_REPORT.md`). Only Pass 2 (LLM-judged) needed the HITL gate S8-3
  added.
- **`mongo_reader`'s grant table is empty** — the fail-closed mechanism
  exists (§4.6/§4.7 of `A2A_PROTOCOL.md`), but no agent is granted `"mongo"`
  access. Closes the door before anyone walks through it; not meant to be
  populated speculatively.
- **Checkpointing / conversation resume** and **the SQL candidate-join
  pushdown** — see §7 (Backlog) below; neither was ever in S8/S9's scope.

### Sprint 9 addendum — Agent I split (optional modularity, ad hoc)

> **Status: DONE.** Not part of Sprint 9's original scope (which split D as
> "the fourth agent" — see S9-3 above) — picked up separately afterward as
> the first of the optional "modularity wave 2" items (I/K/H were flagged as
> the remaining fat nodes; all three are now done — see the K and H
> addenda below).

Same pattern as C/E/G/D: `agents/i_integrator.py` (444 lines) → 90-line thin
node + `services/integrator_service.py` (fetch/normalise FX, M-Pesa, Metropol,
KRA, plus one `fetch_external_data()` orchestrating entry point the node
calls). Simpler than D's split — every existing test (`test_agent_integrator.py`)
calls the private fetch functions directly rather than the full node, so
there was no risk of D's node-calls-service-directly test-patching bug
recurring; still used the one-entry-point design for consistency. No
Celery/worker caller exists for Agent I (verified before starting), so no
`use_cases.py` entrypoint was added — nothing to serve.

Tests: 814 passed, 5 skipped (unchanged count — pure refactor, no new/lost
tests), `ruff check` clean.

**Files:** `agents/i_integrator.py`, `services/integrator_service.py` (new),
`tests/domains/intelligence/test_agent_integrator.py` (import path only).

### Sprint 9 addendum — Agent K split (optional modularity, ad hoc)

> **Status: DONE.** Second of the "modularity wave 2" items (I done above;
> H done below).

Same pattern as I: `agents/k_stockkeeper.py` (402 lines) → 53-line thin node
+ `services/stockkeeper_service.py` (RBAC role resolution, the write-authority
gate, the deterministic snapshot, the CoVe audit of a proposed adjustment,
`_queue_adjustment_proposal`, plus one `run_stock_analysis()` orchestrating
entry point the node calls). K had more test fan-out than I
(`test_agent_k_stockkeeper.py`, `test_agent_k_stockkeeper_cove.py`, and
`tests/integration/test_agent_proposal_workflow.py` all import private
helpers directly), and one test —
`test_node_attaches_deterministic_proposals_and_owns_only_its_key` — patches
`AsyncSessionLocal`/`inventory_valuation`/`low_stock_report`/
`reorder_recommendation`/`generate_structured_content` on the module path
directly, exactly the shape that caused D's node-calls-service-directly
test-patching bug the first time; the one-entry-point design was mandatory
here, not just for consistency, and all three test files' patch targets/
import paths were repointed at `services.stockkeeper_service` accordingly. No
Celery/worker caller exists for Agent K beyond those three test files and
`orchestrator.py` (verified before starting), so no `use_cases.py` entrypoint
was added.

Tests: 814 passed, 5 skipped (unchanged count — pure refactor, no new/lost
tests), `ruff check` clean.

**Files:** `agents/k_stockkeeper.py`, `services/stockkeeper_service.py` (new),
`tests/domains/intelligence/test_agent_k_stockkeeper.py` (patch target only),
`tests/domains/intelligence/test_agent_k_stockkeeper_cove.py` (import path
only), `tests/integration/test_agent_proposal_workflow.py` (import path only).

### Sprint 9 addendum — Agent H split (optional modularity, ad hoc)

> **Status: DONE.** Last of the "modularity wave 2" items — I, K, and H are
> now all split; the wave is closed.

Same pattern as I/K: `agents/h_advisor.py` (309 lines) → 53-line thin node +
`services/advisor_service.py` (RBAC role resolution, the CRM profile lookup,
the RBAC-clipped evidence prompt, the model call, widget allow-listing, and
the S6-5 disclaimer/review-gate guardrails, plus one `build_advice()`
orchestrating entry point the node calls). Both existing test files
(`test_agent_advisor.py`, `test_sprint5.py`) patch `generate_structured_content`
directly on the `agents.h_advisor` module path — the same shape that required
the D/K test-target fix — so both were repointed at `services.advisor_service`;
`test_sprint5.py` needed a second alias (`h_service`) since it also imports
`h_advisor` for `make_h_advisor_node`, which stays in the agent module.
`test_agent_advisor.py`'s standalone `_resolve_user_role` unit tests were
likewise repointed to import from the service module directly. No
Celery/worker caller exists for Agent H beyond those two test files and
`orchestrator.py` (verified before starting), so no `use_cases.py` entrypoint
was added.

Tests: 814 passed, 5 skipped (unchanged count — pure refactor, no new/lost
tests), `ruff check` clean.

**Files:** `agents/h_advisor.py`, `services/advisor_service.py` (new),
`tests/domains/intelligence/test_agent_advisor.py` (import path + patch
target), `tests/domains/intelligence/test_sprint5.py` (patch target only).

### Optional wave — item 7 revisit: unused crypto (2026-09-04)

> **Status: DONE.** Revisited `exchange_cards()` / `issue_task_scoped_vc()` /
> `validate_task_vc()` per S9-1's "revisit only if the trust-domain split
> still hasn't happened" note. It hasn't — still one process, one trust
> boundary — so the disposition is unchanged: **keep, not delete.**

While re-verifying before asking, found `agent_cards.py`'s docstring claimed
`exchange_cards()` is "exercised only by unit tests" — false; grepped
`tests/` and confirmed zero coverage for it (the task-scoped VC functions in
`vc_issuer.py` *are* genuinely tested, `test_vc_issuer.py::
test_validate_task_vc_scope_and_agent_binding`). Fixed the docstring to state
this accurately rather than leave a second stale-test claim in the repo (the
first was S9-1's "these are mandatory" claim, already fixed). No behavior
change, no test change — comment-only.

**Superseded the next day, partially:** this entry's "keep, not delete"
disposition is unchanged, but "currently uncalled" stopped being true for the
task-scoped VC functions specifically — see "Task-scoped VC end-to-end"
below (2026-09-05), which gave `issue_task_scoped_vc`/`validate_task_vc` a
real caller (`require_task_vc`) for audit/defense-in-depth, not because the
trust-domain split this entry was waiting on happened (it hasn't).
`exchange_cards()` itself is unaffected — still uncalled, still untested.

**Files:** `security/agent_cards.py` (docstring only).

### Task-scoped VC end-to-end (2026-09-05) — P0 + P1 + P2

> **Status: P0, P1, and P2 DONE.** Full discovery/blueprint/ticket sequence
> went through Phase 0 (clarifying questions) → Phase 1 (discovery report) →
> Phase 2 (blueprint, 9 tickets P0-P2), then all 9 tickets implemented. P0:
> `require_task_vc()` + flag + metrics, wired into Agent C's Pass 1. P1: E's
> event publish, K/C proposal-creation mint, the Mongo TTL split. P2: B's
> Celery persist (with the TTL-race fix), E's ML retrain self-issuance,
> `verify_own_card()`, and this docs pass. All five write paths named in
> Phase 0's scope answer are now wired; `exchange_cards()` itself remains
> deliberately untouched (still no genuine cross-process boundary for it to
> guard) — see its P2 entry below for the narrower primitive that took its
> place at these call sites.

**Decision (Phase 0):** single-process today, one trust boundary — task VCs
buy audit/defense-in-depth, not a real cross-process guarantee (there isn't
one yet). Default off (`TASK_VC_ENFORCEMENT_ENABLED=False`); shadow mode
mints + validates + records metrics without ever blocking a write, so the
rollout can be observed before anything is enforced.

**What shipped.** `security/vc_issuer.py::require_task_vc()` wraps
`issue_task_scoped_vc`/`validate_task_vc` as one unit (deliberately not two
separable calls — a caller minting for one id and validating against another
by mistake is a real, if unlikely, error this shape rules out structurally).
Wired into both `reconciliation_service.run_reconciliation` (M-Pesa) and
`run_bank_reconciliation` (bank statements) — one `require_task_vc` call per
exact match, inside the existing per-match loop, **before**
`apply_confirmed_match`. A failure skips only that match (and correctly drops
it from `matched_txn_ids`/`matched_inv_ids`/the final `all_matches`, so the
report never claims a settlement that didn't happen) rather than propagating
into `session.begin()`'s existing whole-batch rollback — a real risk flagged
in Phase 1 (a single bad VC could otherwise have undone every other
already-good match in the same run).

New Prometheus counters: `agent_task_vc_issued_total` /
`agent_task_vc_validate_fail_total{agent_id,operation,reason}` (Grafana panels
not added yet — P1 scope per the blueprint).

Tests: `test_vc_issuer.py` gained 4 tests for `require_task_vc` itself (shadow
swallows a mint failure, enforce raises on mint failure, enforce raises on a
real scope mismatch via the actual `validate_task_vc`, success increments the
counter) — Mongo-touching `issue_task_scoped_vc` is mocked, matching how every
other VC-issuance test in this codebase avoids live Mongo;
`validate_task_vc`'s real crypto path is exercised, not stubbed.
`test_bank_reconciliation.py` gained the P0 success-criterion integration
test (enforcement on, a clean match still mints→validates→writes exactly as
the unenforced happy path) plus the batch-isolation test (two matches, one
forced to fail its VC check, only the good one settles — proves the
rollback-blast-radius risk is actually closed, not just designed around).

Full suite: 820 passed, 5 skipped (up from 814 — 6 new tests), `ruff check`
clean on every touched file. `mypy --explicit-package-bases src` clean (the
actual CI gate — confirmed it only checks `src/`, not `tests/`, so two
pre-existing `tests/domains/finance/test_bank_reconciliation.py` mypy gaps
predating this change, and one more of the same already-established shape
introduced by the new tests, are outside the gate and left as-is rather than
fixed opportunistically here).

**Files (P0):** `core/config.py`, `core/metrics.py`,
`security/vc_issuer.py`, `services/reconciliation_service.py`,
`tests/domains/intelligence/test_vc_issuer.py`,
`tests/domains/finance/test_bank_reconciliation.py`.

**P1 — E event publish, K/C proposal-creation mint, Mongo TTL split.**

*E event publish* (`services/anomaly_service.py`): one `require_task_vc` call
right before `make_event_publisher(...).ainvoke(...)`, inside the same
try/except the publish call already sat in — a VC failure degrades exactly
like a broker-unavailable publish failure (`event_published` stays `False`,
the watchdog run still completes). Scoped to a fresh `uuid4()` per call
(there's no existing per-invocation identifier to reuse — unlike C's
`match.transaction_id`, `run_watchdog_analysis` doesn't carry one).

*K/C proposal-creation mint* (`proposal_service.py::create_proposal`): mints
+ validates before the `AgentActionProposal` is even constructed, scoped to
the proposal's own id (generated client-side with `uuid.uuid4()` up front, so
it's available for both the VC and the row itself, rather than waiting on a
DB-assigned default). A distinct claim from `payload_hash` — "this creation
call was authorized" vs. "the payload wasn't altered after creation" — and,
per the hard constraint, **never** touches `approve()`/`reject()`; two new
tests (`test_approve_never_calls_require_task_vc`,
`test_reject_never_calls_require_task_vc`) patch `require_task_vc` to raise
if called during either and assert both still complete normally.

*Mongo TTL split* (`security/vc_issuer.py`): audit VCs (`issue_vc`) and
task-scoped VCs (`issue_task_scoped_vc`) share `trust_log` but now need
different retention (90 days vs. `TASK_VC_RETENTION_DAYS`, 365 by default).
Discovered while implementing that TTL indexes are independent background
sweeps, not a priority chain — simply adding a second index on a new
`retain_until` field wouldn't have worked, since the existing 90-day
`created_at` index (which every document sets) would still delete a
task-scoped document at 90 days regardless. Fixed with **partial** indexes
keyed on `vc_type` (`{"vc_type": "audit"}` / `{"vc_type": "task_scoped"}`) —
first attempt used `retain_until: {"$exists": false}`, which MongoDB's
partial-index filters reject (`$exists: false` compiles to an unsupported
`$not`; only `$exists: true` and a narrow operator set are allowed).
`ensure_trust_log_ttl_index()` also now replaces a same-named index whose
definition has drifted (`IndexOptionsConflict`/`IndexKeySpecsConflict`,
codes 85/86) rather than erroring, so it stays safe to call on every startup
even against an environment that already had the old (non-partial)
`trust_log_ttl_90d` index. Verified against a throwaway MongoDB 7 container
(not mocked — index creation/partial-filter/conflict-handling are server
behaviors a mock can't validate): seeded the old-style index, ran the
function, confirmed both final index definitions via `list_indexes()`,
confirmed a second run is idempotent, and confirmed `issue_task_scoped_vc`
writes `retain_until` as a real BSON Date (not the ISO string `expires_at`
already was) via a real mint+validate roundtrip. No automated test added —
the codebase has no live-Mongo test infra by design (see AGENTS.md §5.3) and
no prior test existed for `ensure_trust_log_ttl_index` either; the container
was torn down after verification.

Tests (P1): `test_agent_watchdog_task_vc.py` (new, 2 tests — E's publish calls
`require_task_vc` first and is skipped when it fails, hermetic since
`run_watchdog_analysis` is session-free by design);
`tests/integration/test_agent_proposal_workflow.py` gained 3 tests
(`create_proposal` mints a task VC scoped to the proposal's own id; `approve`/
`reject` never call it). Full suite: 825 passed, 5 skipped (up from 814 before
P0/P1 — 11 new tests total), `ruff check` and `mypy --explicit-package-bases
src` both clean.

**Files (P1, additional):** `services/anomaly_service.py`,
`proposal_service.py`,
`tests/domains/intelligence/test_agent_watchdog_task_vc.py` (new),
`tests/integration/test_agent_proposal_workflow.py`.

**P2 — B's Celery persist, E's ML retrain, `verify_own_card()`, docs pass.**

*B's Celery persist* (`workers/tasks/batch.py::_run_batch_classification`):
closes the TTL-race gap Phase 1 flagged — the VC is minted **inside this
function**, right before the per-row `UPDATE` loop, not at node-dispatch
time (the node only enqueues `.delay()`; a VC minted there would sit through
an unbounded queue delay and could easily outlive its 5-minute TTL before a
worker ever picked the job up). Scoped to a fresh `batch_id`, not per-row —
the whole persist commits as one unit, so that's the natural write
granularity here (unlike C's per-match loop). A failure means nothing is
persisted this run (`status: "vc_failed"`); safe, since the `FOR UPDATE SKIP
LOCKED` rows release on session close without a commit and the next poll
retries. No existing test covered this function at all before this — new
`tests/workers/test_batch_classification_task_vc.py` (2 tests, real Postgres
via `TestingSessionLocal` repointed onto `batch.AsyncSessionLocal`, same fix
`test_checkpoint_retention.py` needed for the same reason).

*E's ML retrain self-issuance* (`workers/tasks/batch.py::_train_and_upsert_customer`):
unlike E's live event publish or B's dispatch, the weekly retrain is a Celery
beat cron with no per-request agent trigger at all — there's no "agent
mints, someone validates" moment to hang a task VC on the usual way, so this
function mints and validates its own VC immediately before its own
`save_model` write, scoped to the customer being trained. A VC failure and an
insufficient-samples skip share the same `False` return (not disambiguated
there), but not in observability — a VC failure specifically increments
`agent_task_vc_validate_fail_total` and gets its own warning log. No existing
test covered this function either — new
`tests/workers/test_agent_e_retrain_task_vc.py` (3 tests: passes, fails, and
confirms no VC is minted at all when there's no model to save).

*`verify_own_card()`* (`security/agent_cards.py`): Phase 0 approved wiring
card verification into the same mutating call sites as task VCs ("agent →
its own mutating tool call") — not into `exchange_cards()` itself, which has
no sender/receiver pair at any of these single-agent call sites and stays
exactly as documented (two-party, for a genuine future cross-process
handoff). Added a one-party sibling, `verify_own_card(agent_id)`, and called
it from **inside** `require_task_vc()` (first, before minting) so all five
wired call sites get it for free — zero additional call-site changes needed.
3 new tests in `test_agent_cards.py`.

*Docs pass*: fixed `AGENTS.md` §5's HS256 gotcha, which still described a
legacy fallback that was actually removed at `HS256_VC_SUNSET` (S9-1's own
docstring rewrite said as much — the top-level AGENTS.md just hadn't been
updated to match). Added forward-pointers from the S8-1/S8-2 and S9-1
historical narratives above, and from the item-7-revisit backlog bullet, to
this entry — none of their *historical* claims were wrong (task-scoped VCs
genuinely were unused at every point those sections describe), only their
present-tense framing needed a "this changed later, here's where" pointer,
consistent with how the Agent I/K/H "last of four" claims were handled
earlier in this document rather than rewritten in place.

Tests (P2): 5 new (2 batch, 3 retrain) + 3 new (`verify_own_card`). Full
suite: 833 passed, 5 skipped (up from 825 after P1 — 8 new tests),
`ruff check` and `mypy --explicit-package-bases src` both clean.

**Files (P2, additional):** `workers/tasks/batch.py`,
`security/agent_cards.py`, `security/vc_issuer.py` (docstring only — calls
`verify_own_card`), `AGENTS.md`,
`tests/workers/test_batch_classification_task_vc.py` (new),
`tests/workers/test_agent_e_retrain_task_vc.py` (new),
`tests/domains/intelligence/test_agent_cards.py`.

**Staging rollout prep (2026-09-05, post-P2).** Two Grafana panels added to
`monitoring/dashboards/finguard_ai_overview.json` (dashboard `version` 3→4,
tag `d3`→`d4`, `uid` unchanged): "Task VC Issued (rate)"
(`agent_task_vc_issued_total` by `agent_id`/`operation`) and "Task VC
Validate Fail (rate)" (`agent_task_vc_validate_fail_total` by `reason`) —
same panel-pair style as the planner's "Stage Outcome"/"Replan Rate". New
runbook doc, [`TASK_VC_STAGING_BAKE.md`](./TASK_VC_STAGING_BAKE.md), mirrors
`A2A_PLANNER_STAGING_BAKE.md`'s structure but for five wired write paths
instead of three chat intents — notably, shadow mode already mints on every
request regardless of the flag, so the bake's job is watching for a real
*failure* under staging traffic, not proving issuance works (that's already
running). No code changed; `TASK_VC_ENFORCEMENT_ENABLED` is still `False`
everywhere.

### Checkpointing observability (2026-09-05)

> **Status: DONE.** Added the two Prometheus counters the new
> [`CHECKPOINTING_STAGING_BAKE.md`](./CHECKPOINTING_STAGING_BAKE.md) runbook
> needed but didn't have when first written (that runbook initially shipped
> with a "no metrics exist" known gap for this feature — same pattern as the
> planner and task-VC bakes getting their Grafana panels only after their
> own runbooks existed).

`agent_checkpoint_resume_total{outcome}` (`routers/conversations.py`'s
`conversation_resume` — `dispatched`/`not_found`/`not_resumable`) and
`agent_checkpoint_retention_deleted_threads_total`
(`workers/tasks/batch.py::_run_checkpoint_retention_async`). Deliberately did
**not** add a raw checkpoint-write counter — that would mean wrapping
LangGraph's `AsyncPostgresSaver` itself, a bigger and riskier change than
this bake needs; the runbook's existing direct-SQL row-count query already
covers that observation. Two Grafana panels added alongside ("Checkpoint
Resume Outcome (rate)", "Checkpoint Retention — Threads Deleted (7d)" —
dashboard `version` 4→5, tag `d4`→`d5`, `uid` unchanged, same pattern as the
task-VC panel addition above).

Tests: 3 new (`test_conversation_resume_metrics.py` — one per resume
outcome, via the real endpoint + test client, not a mocked router) + 1
extended (`test_checkpoint_retention.py`'s existing purge test now also
asserts the deleted-threads counter). Full suite: 836 passed, 5 skipped (up
from 833), `ruff check` and `mypy --explicit-package-bases src` both clean.

**Files:** `core/metrics.py`, `workers/tasks/batch.py`,
`domains/intelligence/routers/conversations.py`,
`monitoring/dashboards/finguard_ai_overview.json`,
`docs/CHECKPOINTING_STAGING_BAKE.md` (updated — Known gap narrowed, new
Observation queries section),
`tests/domains/intelligence/test_conversation_resume_metrics.py` (new),
`tests/domains/intelligence/test_checkpoint_retention.py`.

### Local Docker bake — A2A planner + task VC (2026-09-05)

> **Status: DONE.** `A2A_PLANNER_ENABLED` and `TASK_VC_ENFORCEMENT_ENABLED`
> flipped and exercised for real against the local `infrastructure/`
> docker-compose stack — not staging, but a genuine live run (real Postgres/
> Mongo/Redis/RabbitMQ containers, real backend + celery-worker processes,
> real Gemini calls), closing several audit residual items concretely rather
> than just by code review. Both flags stay `False` everywhere else
> (config.py default, staging, prod) — this was a local exercise only.

**Docker files.** `docker-compose.yml`'s shared `x-backend-env` anchor
gained `A2A_PLANNER_ENABLED`/`TASK_VC_ENFORCEMENT_ENABLED`/
`LANGGRAPH_CHECKPOINTING_ENABLED`/`CSRF_ENABLED`, each `${VAR:-<config.py's
default>}` — so every backend-family service (API, migrate, celery-worker,
celery-beat, flower) picks up the same value, overridable via a gitignored
`.env` next to the compose files (`infrastructure/.env.example` documents
it). `docker-compose.dev.yml`'s previously-hardcoded host ports
(mongodb/redis/backend/frontend — postgres already had this) became
`${..._HOST_PORT:-<default>}` too, needed because this machine already runs
unrelated containers on 5432/6379/8000/3000.

**What was actually run, live:** `docker compose build` (the cached
`dev`-target image predated `langgraph-checkpoint-postgres` being added to
`pyproject.toml` — a real staleness bug this surfaced, fixed by rebuilding,
not a code change), migrations `0025`→`0026` applied cleanly against a fresh
Postgres, backend booted with both flags confirmed `True` via
`settings.A2A_PLANNER_ENABLED`/`TASK_VC_ENFORCEMENT_ENABLED` read inside the
running container.

- **Planner:** a real "board pack" request (`intent` field — not `message`,
  a request-schema mismatch worth noting since it silently fell back to the
  single-agent default the first time) produced the full 3-stage DAG in
  logs — `[planner] Stage 0: dispatching d_forecaster, f_auditor` →
  `Stage 1: dispatching g_reporter` → `Stage 2: dispatching j_summarizer` →
  `DAG complete` — with real GenUI payloads (CashFlowChart, TaxLiabilityDonut,
  BankabilityScoreRadar) computed from real (empty-ledger) data. Metrics:
  `agent_planner_stage_outcome_total{outcome="run"} 4`,
  `agent_planner_replans_total 0`.
- **Task VC:** `require_task_vc(agent_id="C", ...)` called directly inside
  the live celery-worker container (`TASK_VC_ENFORCEMENT_ENABLED=true`
  confirmed) — minted, self-validated, and wrote a real `trust_log` document
  with `retain_until` as an actual BSON datetime (not the ISO-string
  `expires_at`). `ensure_trust_log_ttl_index()` run against this same live
  Mongo confirmed both partial indexes exist with the correct filters
  (`trust_log_ttl_90d` on `vc_type=audit`, `trust_log_task_vc_retain_until`
  on `vc_type=task_scoped`) — this closes the "confirm TTL index / retain_until
  live on Mongo" residual finding, at least for this local instance.

**Files:** `infrastructure/docker-compose.yml`, `docker-compose.dev.yml`,
`infrastructure/.env.example` (new; `.env` itself is gitignored, not
committed).

---

## 7. Backlog / not-yet-scheduled

- **Multi-jurisdiction tax & credit logic** (F, G). Large, strategic — depends on
  product direction beyond Kenya. Sprint 1's effective-dated config table is the
  enabling foundation; defer the full generalization until it's a committed goal.

- **LangGraph checkpointing / conversation resume** (`LANGGRAPH_CHECKPOINTING_ENABLED`,
  default off). Surfaced in the architectural review that led to Sprint 8/9 but
  never selected into either sprint's scope — not a delivery gap in S8/S9, a
  standalone product decision. **Update:** the feature itself is now fully
  built (config knob + `CHECKPOINT_RETENTION_DAYS`, migration `0025`'s
  `checkpoints`/`checkpoint_blobs`/`checkpoint_writes` tables, the weekly
  `enforce_checkpoint_retention` Celery-beat job, `/status`'s `resumable`
  field + `/resume` endpoint, and the frontend Resume button/mutation) — this
  bullet was never updated to say so when that work landed. What's still
  unmade is the product decision itself: is resumable conversation a
  committed feature, or should `routers/conversations.py`'s resume endpoint
  stay experimental? See
  [`CHECKPOINTING_STAGING_BAKE.md`](./CHECKPOINTING_STAGING_BAKE.md) for the
  staging bake that precedes that decision. Message-history
  reconstructability (§2's hub_writer entry, `AGENTS_REPORT.md`'s "Unbounded
  message history" row) already depends on this flag being on; the resume
  endpoint fails honestly (HTTP 409) when it's off rather than pretending to
  succeed, so nothing is broken by leaving it off in the meantime.

- **Agent C's SQL candidate-join pushdown** — see `DEFERRED_ITEMS_STRATEGY.md`
  item D. Pre-existing, unrelated to S8/S9; indexes shipped (migration `0016`),
  the query itself needs a live DB to validate before it ships.

---

## Suggested sequencing rationale

```
S1 (config) ──▶ S3 (perf tuning needs knobs)
      │          S4 (validation needs tunable params)
      ▼
S2 (decouple) ──▶ makes every later agent change cheaper
S4 ──▶ S5 (feedback loop builds on B evals)
S6 last — vendor-gated + depends on guardrails maturing
S7 — independent of S1-S6; ran opportunistically alongside an external
     harness-design comparison, addenda folded back into S2/S3/S4 above
S8 — independent of S1-S7; ran from an architectural review of the
     intelligence domain, not a con in AGENTS_REPORT.md; extends S7's
     tool-grant pattern (mongo) and VC/trust-log work (payload integrity)
S9 — closes the gaps a follow-up audit found in S8 (doc drift, no mutation
     matrix, D unsplit, planner never exercised end-to-end); extends S8's
     TOOL_GRANTS pattern to a new axis (mutation kind, not resource) and
     finishes S8's agent-decomposition pass
```

**If you can only do two sprints:** run **S1** then **S2** — together they remove the
two structural weaknesses (hard-coded constants, persistence coupling) that make every
other fix more expensive, at the lowest risk.
