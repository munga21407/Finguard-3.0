# Finguard 3.0 — Scaling & Data-Intensive Architecture Notes

> Analysis of four data-intensive-systems patterns proposed for Finguard, with a
> per-pattern verdict and **explicit "revisit when X" triggers** so we build for
> the scale we have, not the scale we imagine. Captured 2026-06-14.

## Context that frames every decision

Finguard targets Kenyan SMEs. Realistic write volume is **hundreds-to-low-thousands**
of ledger entries / M-Pesa transactions per business per day — not millions. The
current stack is **RabbitMQ + Celery + PostgreSQL + MongoDB** (no Kafka). Three of
the four proposals below assume a Kafka/Redpanda backbone and solve problems that
appear 10²–10³× past our likely load. Each one trades a working component for
standing operational complexity. The bar for adopting is therefore: *does it solve
a problem we actually have now, on the stack we actually run?*

The existing **transactional outbox + idempotent consumers + dual-store (Postgres
ACID / Mongo read-model)** design is already the textbook answer for a
data-intensive financial system at SME scale.

---

## 1. Log-based Change Data Capture (Debezium) — DEFER

**Proposal:** Replace 5s outbox polling with Debezium tailing the Postgres WAL.

**Assessment — weakest fit:**
- The polling cost is overstated: `SELECT … LIMIT 100 FOR UPDATE SKIP LOCKED` every
  5s on a partial index (`WHERE published = false`) is nearly free.
- **Stack mismatch is the blocker.** Debezium is Kafka-Connect-native. Routing it to
  RabbitMQ means Debezium Server (the less-trodden path) or adding Kafka *alongside*
  RabbitMQ — large new infrastructure to replace ~60 lines of `projector.py`.
- CDC does not even remove the outbox. Raw WAL emits *row diffs*; to recover
  semantic events you use the **Outbox Event Router** — i.e. you keep the outbox and
  Debezium reads *it*. So this is additive complexity, not a replacement.

**Cheaper alternative if latency ever bites:** switch the projector from fixed-interval
polling to Postgres `LISTEN/NOTIFY`-driven wakeups — sub-second latency, zero new infra.

**Revisit when:** event-propagation latency (commit → broker) becomes a *measured*
product problem AND we have already moved to a Kafka/Redpanda backbone for other reasons.

---

## 2. Event Sourcing for the financial ledger — ADOPT (scoped) ✅ IN PROGRESS

**Proposal:** Model state as an append-only sequence of domain events
(`InvoiceIssued`, `PaymentApplied`, `CreditNoteGenerated`) and derive current state
by folding them; project to a fast read model.

**Assessment — most aligned with a financial / KRA-compliance product:**
- We are already half-way: `ledger_entries` (credit/debit rows) is effectively an
  append-only double-entry log, and `payments` rows are immutable. The mutable
  surface is really just `invoices` (`amount_paid`, `balance_due`, `status`).
- We already run the *projection* half of the pattern (outbox → async projection →
  `intelligence_hub`).
- **Do NOT event-source the whole system.** Full ES adds permanent event-versioning,
  replay tooling, and snapshotting cost. The payoff concentrates where "how did this
  balance get here" is a compliance question: **payment application to invoices.**

**What we are building (this iteration):**
- An append-only `invoice_events` table — the event log of record for the invoice
  lifecycle (`invoice_issued`, `payment_applied`).
- A pure `fold_invoice_events()` that derives `(total, amount_paid, balance_due,
  status)` from the event sequence.
- The `invoices` row becomes a **synchronous projection** of that fold (kept in the
  same transaction, so the `CHECK (balance_due = total - amount_paid)` constraint and
  the `FOR UPDATE` serialization are preserved — no behavioural regression).
- A `GET /invoices/{id}/events` endpoint exposing the history + a reconstruction so an
  auditor can verify the materialized row equals the fold.

**Deliberately deferred within this pattern:**
- **Async** projection (à la `intelligence_hub`) — kept synchronous for now to retain
  ACID guarantees and the CHECK constraint. Move async only if invoice writes become
  a latency hotspot.
- **Snapshotting** — fold replays full history per write. Fine at SME scale (few
  events per invoice). Add snapshots only if an invoice routinely exceeds ~10³ events.
- **`credit_note_applied` / `invoice_cancelled`** events — enum/extension points noted
  but only wired when those flows exist.

**Revisit when:** an invoice routinely accumulates >10³ events (snapshotting), or
invoice-write latency from synchronous folding shows up in traces (async projection).

---

## 3. Stream processing for Agent E (anomaly detection) — DEFER

**Proposal:** Move from Celery background tasks to a stateful stream processor
(Faust / Kafka) maintaining rolling transaction windows.

**Assessment:**
- **Faust is effectively abandoned**; the live path is the `faust-streaming` fork, and
  it still wants Kafka.
- The real latency source is not Celery vs. streams — it is that Agent E boots
  `IsolationForest` + RapidFuzz + an LLM narrative + VC issuance per trigger. A
  windowing stream processor front-runs none of that.
- The useful nugget — windowed **velocity** detection ("N transactions in 10 min for a
  customer") — needs no streaming platform: a **Redis sorted-set sliding window**
  (`ZADD` by ts, `ZCOUNT` over window) gives the same signal on infra we already run,
  complementing the existing idempotency-key consumer.

**Revisit when:** we centralize many tenants into one high-throughput pipeline and
need native event-time windowing / out-of-order handling.

---

## 4. PostgreSQL table partitioning — ROADMAP (the strongest, but not yet)

**Proposal:** Range-partition large tables by `created_at`; drop old partitions for
retention.

**Assessment — best of the four; native, no new infra:**
- **Retention win is real and elegant.** `enforce_data_retention` currently does
  bounded `DELETE` batches over 7-year-old rows (I/O-heavy, bloat-generating,
  `VACUUM`-dependent). `DROP TABLE ledger_entries_2019_05` is instant and clean.
- The index-exceeds-RAM argument is true but premature at SME volume.
- Real cost: `created_at` must enter the PK/unique constraints, migrating existing
  tables to partitioned is non-trivial, and partition creation must be automated
  (`pg_partman` or a scheduled job) or inserts fail on a missing future partition.

**Plan:** month-range partitions on `ledger_entries`, `mpesa_transactions`,
`bank_statement_lines` — driven by retention ergonomics, not the RAM argument.

**Revisit when:** any of these tables exceeds ~10–50M rows, OR retention `DELETE`
batches start appearing in slow-query logs.

---

## Summary

| # | Pattern | Verdict | Trigger to revisit |
|---|---|---|---|
| 1 | CDC / Debezium | Skip | Measured latency problem *and* already on Kafka |
| 2 | Event Sourcing (invoices/payments) | **Adopt, scoped** | >10³ events/invoice; write-latency hotspot |
| 3 | Stream processing (Agent E) | Skip | Multi-tenant high-throughput consolidation |
| 4 | Table partitioning | Roadmap | Table >10–50M rows; retention DELETEs in slow log |

**Lower-hanging fruit (do before any of the above):** partial index on
`outbox_events(published) WHERE published = false`; Redis sliding-window velocity
check in the watchdog consumer; partitioning when retention actually hurts.
