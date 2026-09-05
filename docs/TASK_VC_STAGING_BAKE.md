# Task-Scoped VC Enforcement — Staging Bake & Go/No-Go Runbook

*Companion to
[`AGENTS_REMEDIATION_SPRINTS.md`](./AGENTS_REMEDIATION_SPRINTS.md)'s
"Task-scoped VC end-to-end" entry (P0-P2), which wired
`security/vc_issuer.py::require_task_vc()` into five write paths — Agent C
Pass 1, Agent E's anomaly-event publish, Agent E's model retrain, Agent K/C
proposal creation, and Agent B's batch classification persist. That work
made flipping `TASK_VC_ENFORCEMENT_ENABLED` safe to attempt; it did not
decide whether or when to flip it. This is the how-to for making that
decision.*

> **Status:** `TASK_VC_ENFORCEMENT_ENABLED` is `False` by default in
> `config.py` and in every environment as of this writing. This runbook does
> not change that — it's the procedure for a staging bake, not an approval
> to ship one.

## What flipping the flag actually changes

All five wired call sites already mint + self-validate a task-scoped VC
**today**, flag or not — that's shadow mode, and it's what's live everywhere
right now. The flag only controls what happens on a *failure*:

| | Shadow (flag off, current default) | Enforce (flag on) |
|---|---|---|
| VC mint/validate fails | Logged (`agent_task_vc_validate_fail_total` increments), write proceeds anyway | Write is skipped/blocked — see the per-path behavior below |

So the bake isn't observing whether VCs get issued (they already are,
everywhere, right now) — it's observing whether real staging traffic ever
*fails* the check, and if it does, whether the resulting skip/block behavior
is acceptable.

**Per-path behavior when enforcement blocks a write:**

| Path | On failure |
|---|---|
| C Pass 1 (`reconciliation_service`) | Skips only that one match; the rest of the batch still settles |
| E event publish (`anomaly_service`) | `event_published=False`, same as a broker-unavailable failure today — the watchdog run still completes |
| E model retrain (`batch.py::_train_and_upsert_customer`) | That one customer's model isn't saved this run (same `False` return as insufficient-samples) |
| K/C proposal creation (`proposal_service.create_proposal`) | The whole `create_proposal` call raises — no proposal is persisted, propagates to the calling agent node |
| B batch persist (`batch.py::_run_batch_classification`) | The whole batch isn't persisted (`status: "vc_failed"`); rows stay unclassified, unlocked for the next poll |

## Prerequisites (already true, verified before writing this)

- All five call sites are covered by tests exercising both the pass and fail
  paths (`test_vc_issuer.py`, `test_bank_reconciliation.py`,
  `test_agent_watchdog_task_vc.py`, `test_agent_proposal_workflow.py`,
  `test_batch_classification_task_vc.py`, `test_agent_e_retrain_task_vc.py`).
- Metrics exist and are on the Grafana dashboard
  (`monitoring/dashboards/finguard_ai_overview.json`):
  `agent_task_vc_issued_total{agent_id,operation}` and
  `agent_task_vc_validate_fail_total{agent_id,operation,reason}` — "Task VC
  Issued (rate)" and "Task VC Validate Fail (rate)" panels.
- `verify_own_card()` runs first, inside `require_task_vc`, on every one of
  these five call sites — a `reason=PermissionError` in the fail-rate panel
  means the CA signing key (`FINGUARD_CA_PRIVATE_KEY_HEX` / the dev-derived
  fallback) is misconfigured for this environment, not a VC-logic bug.
- Beyond the test suite, `require_task_vc` under enforce mode has now been
  run for real against a local Docker stack (2026-09-05) — real Mongo, real
  Ed25519 signing, a real `trust_log` write with `retain_until` as an actual
  datetime, and `ensure_trust_log_ttl_index()`'s two partial indexes
  confirmed present with the right filters. See
  `AGENTS_REMEDIATION_SPRINTS.md`'s "Local Docker bake" entry.
  `infrastructure/.env.example` documents how to reproduce it
  (`TASK_VC_ENFORCEMENT_ENABLED=true` picked up by `docker-compose.yml`'s
  shared env anchor) — a local Docker bake isn't a substitute for the
  staging bake below (different Mongo, different traffic), but it's one
  more layer of confidence going in.

## Known gap (read before running the bake)

Because shadow mode already mints on every request, staging traffic *before*
this bake even starts should already be producing `agent_task_vc_issued_total`
data (check the panel first — if it's already non-zero, the "shadow" baseline
is free). What you can't get for free is a **failure** — MongoDB in staging
being reachable and healthy means the happy path basically always succeeds,
so a natural failure may simply never occur during the bake window. Don't
mistake "zero failures observed" for "the failure path works" — the negative
tests already prove that at the unit/integration level (see Prerequisites);
the bake's job is to prove *real* traffic doesn't trip it unexpectedly, not
to manufacture a failure.

If you want to affirmatively exercise the enforce-mode failure path in
staging (recommended at least once, not required every bake), the simplest
lever is a deliberate Mongo blip: briefly point `MONGODB_URL` at an
unreachable host for one manual invocation of one path (e.g.
`batch.run_batch_reconciliation`, see Staging checklist), confirm it degrades
per the per-path table above, then restore the real URL. Do this deliberately
and briefly — it's a real (if temporary) staging Mongo outage.

## Staging checklist

1. Confirm the Grafana panels already show `agent_task_vc_issued_total`
   traffic from shadow mode (see Known gap) — if completely flat, staging
   traffic isn't reaching these paths at all yet; trigger them manually
   first (below) before flipping the flag, so you have a shadow-mode
   baseline to compare against.
2. Set `TASK_VC_ENFORCEMENT_ENABLED=true` in staging (see Env snippet).
   Restart/redeploy the service — `settings` is loaded once at process
   startup, so a running process won't pick up the env var change without
   one.
3. Exercise all five paths (Manual triggers below), watching Grafana +
   service logs after each.
4. Watch the observation window (Observation queries below).
5. Fill in the Go/No-Go template using the per-path table.
6. **If "no":** flip the env var back to `false`. Shadow mode keeps running
   regardless — there's no reason to touch anything else.

## Manual triggers (one per wired path)

Celery-task paths — same manual-invocation convention as
`enforce_checkpoint_retention` (see `AGENTS_REMEDIATION_SPRINTS.md`'s
checkpointing entry):

```bash
celery -A src.workers.tasks.celery_app call batch.run_batch_reconciliation        # C Pass 1 (M-Pesa)
celery -A src.workers.tasks.celery_app call batch.run_batch_bank_reconciliation   # C Pass 1 (bank)
celery -A src.workers.tasks.celery_app call batch.classify_unclassified_ledger_entries  # B
celery -A src.workers.tasks.celery_app call batch.retrain_agent_e_models          # E retrain (all customers)
celery -A src.workers.tasks.celery_app call batch.fit_agent_e_model --args='["<customer_uuid>"]'  # E retrain (one customer)
```

Live-chat paths — `POST /api/v1/intelligence/conversation` with
`"mode": "actions"`:

- **E event publish** — a request that produces a CRITICAL/anomalous
  budget-watchdog read (see `agents/e_watchdog.py` / `watchdog_consumer.py`
  for what triggers this in practice); confirm in logs the node reached the
  `make_event_publisher(...).ainvoke(...)` line, not just the VC mint.
- **K/C proposal creation** — a stock-adjustment request to Agent K
  (`context["stock_action"]` with `movement_type: "adjustment"`, see
  `services/stockkeeper_service.py`) or a Pass-2 fuzzy reconciliation match
  landing via `_propose_semantic_matches`; confirm a row appears in
  `agent_action_proposals`.

## Env snippet

```bash
railway variables set TASK_VC_ENFORCEMENT_ENABLED=true --environment staging --service <backend-service-name>

# to revert:
railway variables set TASK_VC_ENFORCEMENT_ENABLED=false --environment staging --service <backend-service-name>
```

`config.py`'s default stays `False` — nothing here touches committed code.

## Observation queries / dashboard notes

```promql
sum by (agent_id, operation) (rate(agent_task_vc_issued_total[5m]))        # "Task VC Issued (rate)" panel
sum by (reason) (rate(agent_task_vc_validate_fail_total[5m]))              # "Task VC Validate Fail (rate)" panel
```

A healthy bake looks like all five `operation` values appearing in the
issued-rate panel (proof each path was actually exercised) and the
fail-rate panel staying at zero for the duration — any non-zero point is
worth reading the surrounding logs for (which path, which `reason`) before
deciding go/no-go, not just noting the number.

**Retention:** task-scoped VC `trust_log` documents now carry a `retain_until`
365 days out (`TASK_VC_RETENTION_DAYS`) instead of the shared 90-day index —
nothing to watch during the bake itself, just confirms the doc trail from
this bake will still be there next time someone looks.

## Go/No-Go decision template

```markdown
# Task-Scoped VC Enforcement Staging Bake — Go/No-Go

Date: __________   Observed by: __________   Window: ______ (hours)

| Path                          | Exercised? | Issued (count) | Validate-fail (count) | Notes |
|--------------------------------|------------|-----------------|--------------------------|-------|
| C Pass 1 (reconciliation.apply)          |            |                 |                          |       |
| E event publish (watchdog.anomaly_publish)|            |                 |                          |       |
| E model retrain (watchdog.model_retrain) |            |                 |                          |       |
| K/C proposal creation (*.create_proposal)|            |                 |                          |       |
| B batch persist (classify.batch_persist) |            |                 |                          |       |

| Criterion                                   | Threshold / expectation                        | Observed | Pass? |
|-----------------------------------------------|-------------------------------------------------|----------|-------|
| All five paths exercised at least once        | Each shows a non-zero `issued` count            |          |       |
| Validate-fail rate                            | Zero, or every non-zero point explained by a deliberate test (see Known gap) |          |       |
| `reason=PermissionError` count                 | Zero (a non-zero count means the CA key is misconfigured for this environment — investigate before going further, independent of the rest of this bake) |          |       |
| No unexpected write-skips in logs             | Every skip/block traces to an explained validate-fail above |          |       |

**Decision:** ☐ Go (enable in prod)   ☐ No-go (flag stays off, no other changes)

Notes / anomalies observed:
```

## On failure

Leave the flag off. Shadow mode (mint + validate + log + metrics, never
blocking) keeps running regardless — there's no reason to touch anything
else; it's already the current, unconditional behavior of all five call
sites.

## On success

Repeat the env-var flip in prod (same command, `--environment production`),
after a rollout window you're comfortable with — this runbook covers staging
only; treat a prod rollout as its own, separate decision using the same
template.
