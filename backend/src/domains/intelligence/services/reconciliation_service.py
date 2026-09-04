"""
Reconciliation pipeline — matches floating settlements to open invoices.

Framework-agnostic core for Agent C (Reconciliation Detective): everything here
is plain async Python with no LangGraph dependency, so it's callable directly
by the LangGraph node (``agents.c_reconciler.make_c_reconciler_node``) and by
the Celery batch tasks (``workers.tasks.batch``) alike — see ``run_reconciliation``
/ ``run_bank_reconciliation``.

Two-pass matching algorithm:

  Pass 1 (Deterministic): Exact match on amount (±KES 1), date (±2 days), and
      reference substring — no LLM required.

  Pass 2 (Semantic): For residual unmatched transactions, rapidfuzz pre-filters
      candidates (token-sort ratio ≥ 65) which are then scored by the model to
      confirm or reject each pairing based on reference semantics, amounts, and
      phone-number identity signals.

Pass 1 matches settle immediately — invoices are updated to "paid" or
"partially_paid" with a row-level FOR UPDATE lock to prevent race conditions
from concurrent webhook events. Pass 2 matches are an LLM judgment call, not a
deterministic one, so they are never applied inline: each is queued as an
``AgentActionProposal`` (action_type "reconciliation.match") and only settles
once a human approves it via ``ProposalService`` — see
``_propose_semantic_matches`` and ``proposal_service.ACTION_RECONCILIATION_MATCH``.

Performance (Sprint 3):
  * Pass 1 buckets invoices by floored balance so each transaction only scans
    near-amount candidates — O(txn + invoice) instead of the old O(txn × invoice)
    nested loop.
  * The the model candidate cap is configurable (``ReconcilerTuning.pass2_candidate_cap``).
  * Migration ``0016`` adds the fetch-supporting indexes:
    ``(mpesa_transactions is_reconciled, created_at)``,
    ``(invoices status, balance_due, due_date)``,
    ``(bank_statement_lines is_reconciled, review_status, date)``.

SQL candidate-join pushdown (design note — deferred, needs a live DB to validate):
  Settlement (``FinanceService.apply_reconciled_payment``) is the authoritative
  safety gate — it locks each invoice ``FOR UPDATE`` and clamps the applied amount
  to the outstanding balance (returning None if already settled), so a
  double-match can never over-credit.  The up-front ``FOR UPDATE SKIP LOCKED`` on
  the invoice batch is therefore an *optimisation* (avoid concurrent runs doing
  redundant work), not a correctness requirement.  That makes a Pass-1 candidate
  join safe to add:

      WITH txns AS (
        SELECT id, amount, created_at, bill_ref FROM mpesa_transactions
        WHERE is_reconciled = FALSE ORDER BY created_at LIMIT :lim
        FOR UPDATE SKIP LOCKED)
      SELECT t.id, i.id, i.invoice_number, i.balance_due, i.due_date
      FROM txns t JOIN invoices i
        ON i.status IN ('SENT','OVERDUE') AND i.balance_due > 0
       AND abs(t.amount - i.balance_due) <= :tol
       AND (i.due_date IS NULL
            OR abs(EXTRACT(EPOCH FROM (t.created_at - i.due_date))/86400) <= :win)
      FOR UPDATE OF i SKIP LOCKED;

  Python then applies the ref-substring filter + first-match dedup on the (small)
  candidate set.  Pass 2 (rapidfuzz) still needs the residual invoice set, so it
  loads invoices lazily only when unmatched txns with a bill_ref remain — the case
  where the pushdown pays off is high open-invoice volume (near the 500 cap) where
  most matches are exact.  A full fuzzy pushdown would additionally need pg_trgm +
  a GIN trigram index on invoice_number.  Ship behind a config flag and validate
  match-equivalence against ``test_reconciler_pass1_bucketing`` + a concurrency
  test before making it the default.
"""
from __future__ import annotations

import json
import math
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

import structlog
from rapidfuzz import fuzz
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.domains.finance.models import Payment
from src.domains.finance.service import FinanceService
from src.domains.finance.types import VaultType
from src.domains.intelligence.db_tuning import refresh_agent_tuning_from_db
from src.domains.intelligence.llm_client import generate_structured_content
from src.domains.intelligence.models import AgentActionProposal, ProposalStatus
from src.domains.intelligence.prompts.c_reconciler import RECONCILER_PASS2_SYSTEM
from src.domains.intelligence.schemas import (
    ReconciliationCandidate,
    ReconciliationMatch,
    ReconciliationReport,
    ReconciliationScoringResult,
)
from src.domains.intelligence.tuning import get_reconciler_tuning

logger = structlog.get_logger(__name__)

# Batch sizes and match thresholds (externally configurable — see
# tuning.ReconcilerTuning).
_rc = get_reconciler_tuning()
_TXN_BATCH = _rc.txn_batch              # M-Pesa transactions per reconciliation run
_INV_LIMIT = _rc.inv_limit              # Max open invoices to load
_FUZZY_THRESHOLD = _rc.fuzzy_threshold  # rapidfuzz token_sort_ratio min for Pass 2 candidacy
_SEMANTIC_THRESHOLD = _rc.semantic_threshold  # the model match_score min to confirm a match
_FUZZY_MATCH_BOUNDARY = _rc.fuzzy_match_boundary  # >= this -> "fuzzy", below -> "semantic"
_AMOUNT_TOLERANCE = _rc.amount_tolerance_kes  # Pass 1 exact-amount tolerance (KES)
_DATE_WINDOW_DAYS = _rc.date_window_days  # Pass 1 date-proximity window (days)
_PASS2_CANDIDATE_CAP = _rc.pass2_candidate_cap  # max fuzzy candidates sent to the model


def _apply_reconciler_tuning() -> None:
    """Rebind module-level batch/threshold constants from current tuning.

    Called at the top of each reconciliation run (after the DB overlay refresh)
    so a runtime override in ``finguard.agent_config`` applies without a restart.
    Synchronous (no awaits) → atomic under asyncio w.r.t. concurrent runs.
    """
    global _TXN_BATCH, _INV_LIMIT, _FUZZY_THRESHOLD, _SEMANTIC_THRESHOLD
    global _FUZZY_MATCH_BOUNDARY, _AMOUNT_TOLERANCE, _DATE_WINDOW_DAYS, _PASS2_CANDIDATE_CAP
    rc = get_reconciler_tuning()
    _TXN_BATCH = rc.txn_batch
    _INV_LIMIT = rc.inv_limit
    _FUZZY_THRESHOLD = rc.fuzzy_threshold
    _SEMANTIC_THRESHOLD = rc.semantic_threshold
    _FUZZY_MATCH_BOUNDARY = rc.fuzzy_match_boundary
    _AMOUNT_TOLERANCE = rc.amount_tolerance_kes
    _DATE_WINDOW_DAYS = rc.date_window_days
    _PASS2_CANDIDATE_CAP = rc.pass2_candidate_cap


# ---------------------------------------------------------------------------
# Matching helpers
# ---------------------------------------------------------------------------

def _amount_match(paid: float, due: float, tolerance: float | None = None) -> bool:
    tol = _AMOUNT_TOLERANCE if tolerance is None else tolerance
    return abs(paid - due) <= tol


def _date_match(txn_date: Any, due_date: Any, window_days: int | None = None) -> bool:
    if due_date is None:
        return True
    window = _DATE_WINDOW_DAYS if window_days is None else window_days
    try:
        if hasattr(txn_date, "date"):
            t = txn_date.date()
        else:
            t = datetime.fromisoformat(str(txn_date)).date()
        if hasattr(due_date, "date"):
            d = due_date.date()
        else:
            d = datetime.fromisoformat(str(due_date)).date()
        return abs((t - d).days) <= window
    except Exception:
        return True  # unparseable dates — let other criteria decide


def _ref_match(bill_ref: str | None, invoice_number: str) -> bool:
    if not bill_ref:
        return False
    b = bill_ref.lower().strip()
    i = invoice_number.lower().strip()
    if b in i or i in b:
        return True
    # Check if any meaningful token from bill_ref appears in the invoice number
    return any(token in i for token in b.split() if len(token) >= 3)


# ---------------------------------------------------------------------------
# Pass 1 — Deterministic exact matching
# ---------------------------------------------------------------------------

def _bucket_invoices_by_amount(
    invoices: list[dict[str, Any]],
) -> dict[int, list[tuple[int, dict[str, Any]]]]:
    """Index invoices into integer KES buckets keyed by ``floor(balance_due)``.

    Lets Pass 1 look up only the near-amount invoices for a transaction instead
    of scanning all of them — turning the exact pass from O(txn × invoice) into
    roughly O(txn + invoice).  Each entry keeps the invoice's original index so
    candidates can be re-sorted into scan order (preserving first-match
    determinism identical to the old nested loop).
    """
    buckets: dict[int, list[tuple[int, dict[str, Any]]]] = defaultdict(list)
    for idx, inv in enumerate(invoices):
        buckets[int(math.floor(float(inv["balance_due"])))].append((idx, inv))
    return buckets


def _pass1_exact(
    transactions: list[dict[str, Any]],
    invoices: list[dict[str, Any]],
) -> tuple[list[ReconciliationMatch], set[str], set[str]]:
    matched_txn_ids: set[str] = set()
    matched_inv_ids: set[str] = set()
    matches: list[ReconciliationMatch] = []

    buckets = _bucket_invoices_by_amount(invoices)
    tol = _AMOUNT_TOLERANCE

    for txn in transactions:
        amount = float(txn["amount"])
        # Only invoices whose balance rounds near the paid amount can match on
        # amount; the ±1 margin guards floor() boundaries (the precise check is
        # still _amount_match below).
        lo = int(math.floor(amount - tol)) - 1
        hi = int(math.floor(amount + tol)) + 1
        candidates: list[tuple[int, dict[str, Any]]] = []
        for key in range(lo, hi + 1):
            candidates.extend(buckets.get(key, ()))
        candidates.sort(key=lambda pair: pair[0])  # original scan order

        for _idx, inv in candidates:
            if inv["id"] in matched_inv_ids:
                continue
            if not _amount_match(amount, inv["balance_due"]):
                continue
            if not _date_match(txn["created_at"], inv["due_date"]):
                continue
            if not _ref_match(txn.get("bill_ref"), inv["invoice_number"]):
                continue

            status = (
                "paid"
                if amount >= inv["balance_due"] - 0.01
                else "partially_paid"
            )
            matches.append(
                ReconciliationMatch(
                    transaction_id=txn["id"],
                    invoice_id=inv["id"],
                    match_type="exact",
                    match_score=1.0,
                    amount=amount,
                    new_invoice_status=status,
                )
            )
            matched_txn_ids.add(txn["id"])
            matched_inv_ids.add(inv["id"])
            break

    return matches, matched_txn_ids, matched_inv_ids


# ---------------------------------------------------------------------------
# Pass 2 — rapidfuzz + the model semantic matching
# ---------------------------------------------------------------------------

def _build_fuzzy_candidates(
    transactions: list[dict[str, Any]],
    invoices: list[dict[str, Any]],
    matched_txn_ids: set[str],
    matched_inv_ids: set[str],
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for txn in transactions:
        if txn["id"] in matched_txn_ids:
            continue
        bill_ref = (txn.get("bill_ref") or "").strip()
        if not bill_ref:
            continue
        for inv in invoices:
            if inv["id"] in matched_inv_ids:
                continue
            score = fuzz.token_sort_ratio(bill_ref, inv["invoice_number"])
            if score >= _FUZZY_THRESHOLD:
                candidates.append(
                    {
                        "transaction_id": txn["id"],
                        "invoice_id": inv["id"],
                        "bill_ref": bill_ref,
                        "invoice_number": inv["invoice_number"],
                        "amount_paid": txn["amount"],
                        "amount_due": inv["balance_due"],
                        "phone": txn.get("phone", ""),
                        "rapidfuzz_score": score,
                    }
                )
    return candidates


async def _llm_score_candidates(
    candidates: list[dict[str, Any]],
) -> ReconciliationScoringResult:
    prompt = (
        f"{RECONCILER_PASS2_SYSTEM}\n\n"
        "## Candidate Matches (JSON)\n"
        f"{json.dumps(candidates[:_PASS2_CANDIDATE_CAP], indent=2)}\n\n"
        "Score each candidate. Return only those with match_score >= 0.60. "
        "Deduplicate so each transaction_id and invoice_id appears at most once."
    )
    return await generate_structured_content(
        prompt, ReconciliationScoringResult, temperature=0.0
    )


async def _pass2_semantic(
    transactions: list[dict[str, Any]],
    invoices: list[dict[str, Any]],
    matched_txn_ids: set[str],
    matched_inv_ids: set[str],
) -> list[ReconciliationMatch]:
    candidates = _build_fuzzy_candidates(
        transactions, invoices, matched_txn_ids, matched_inv_ids
    )
    if not candidates:
        return []

    try:
        scored = await _llm_score_candidates(candidates)
    except Exception as exc:
        logger.error("reconciliation_service: the model Pass 2 scoring failed", error=str(exc))
        return []

    matches: list[ReconciliationMatch] = []
    seen_txn: set[str] = set()
    seen_inv: set[str] = set()

    sorted_candidates: list[ReconciliationCandidate] = sorted(
        scored.candidates, key=lambda c: c.match_score, reverse=True
    )

    txn_map = {t["id"]: t for t in transactions}
    inv_map = {i["id"]: i for i in invoices}

    for cand in sorted_candidates:
        if cand.transaction_id in seen_txn or cand.invoice_id in seen_inv:
            continue
        if cand.match_score < _SEMANTIC_THRESHOLD:
            continue
        txn = txn_map.get(cand.transaction_id)
        inv = inv_map.get(cand.invoice_id)
        if not txn or not inv:
            continue

        status = (
            "paid" if txn["amount"] >= inv["balance_due"] - 0.01 else "partially_paid"
        )
        # rapidfuzz-only matches score ≥ boundary; model-confirmed lower scores are "semantic"
        match_type = "fuzzy" if cand.match_score >= _FUZZY_MATCH_BOUNDARY else "semantic"
        matches.append(
            ReconciliationMatch(
                transaction_id=cand.transaction_id,
                invoice_id=cand.invoice_id,
                match_type=match_type,
                match_score=cand.match_score,
                amount=txn["amount"],
                new_invoice_status=status,
            )
        )
        seen_txn.add(cand.transaction_id)
        seen_inv.add(cand.invoice_id)

    return matches


# ---------------------------------------------------------------------------
# DB persistence
# ---------------------------------------------------------------------------

async def apply_confirmed_match(
    session: AsyncSession, match: ReconciliationMatch, occurred_at: datetime
) -> Payment | None:
    """Persist a confirmed match as an event-sourced Payment linked to the invoice.

    Delegates to ``FinanceService.apply_reconciled_payment`` so the settlement
    creates a Payment row (tagged with its rail) + a ``payment_applied`` event and
    re-projects the invoice — identical bookkeeping to a manual cash payment — and
    marks the raw settlement (M-Pesa txn / bank line) reconciled.  Flush-only —
    the caller owns commit/rollback, whether that's ``run_reconciliation``'s
    ``session.begin()`` (Pass 1, called inline) or ``ProposalService.approve``
    (Pass 2, replayed on human sign-off — see ``ACTION_RECONCILIATION_MATCH``).

    Returns ``None`` if the invoice was already fully settled (e.g. paid another
    way while a Pass 2 match sat pending review) — the caller must not treat that
    as success.
    """
    service = FinanceService(session)
    if match.source == "bank":
        return await service.apply_reconciled_payment(
            invoice_id=match.invoice_id,
            amount=match.amount,
            vault=VaultType.BANK,
            occurred_at=occurred_at,
            bank_line_id=match.transaction_id,
        )
    return await service.apply_reconciled_payment(
        invoice_id=match.invoice_id,
        amount=match.amount,
        vault=VaultType.MPESA,
        occurred_at=occurred_at,
        mpesa_trans_id=match.transaction_id,
    )


async def _pending_reconciliation_proposal_exists(
    session: AsyncSession, transaction_id: str
) -> bool:
    """True if a Pass 2 match for ``transaction_id`` is already awaiting review.

    Pass 2 rescans the same unreconciled rows every batch (a semantic match
    doesn't flip ``is_reconciled`` until a human approves it), so without this
    guard each run would queue a fresh duplicate proposal for the same
    transaction. Keyed on the JSONB payload's ``transaction_id`` rather than a
    schema change.
    """
    result = await session.execute(
        select(AgentActionProposal.id)
        .where(
            AgentActionProposal.action_type == "reconciliation.match",
            AgentActionProposal.status == ProposalStatus.PROPOSED,
            AgentActionProposal.payload["transaction_id"].astext == transaction_id,
        )
        .limit(1)
    )
    return result.scalar_one_or_none() is not None


async def _propose_semantic_matches(
    session: AsyncSession,
    matches: list[ReconciliationMatch],
    occurred_at_by_txn: dict[str, Any],
) -> None:
    """Queue each Pass 2 (fuzzy/semantic) match for human sign-off.

    Unlike Pass 1's deterministic exact matches (auto-applied inline, see
    ``run_reconciliation``), a Pass 2 match is an LLM judgment call being used to
    move real ledger state — so it lands as an ``AgentActionProposal`` instead of
    settling immediately.  Runs *after* the caller's ``session.begin()`` block has
    committed (``ProposalService.create_proposal`` manages its own transaction and
    must not be nested inside one — see its docstring).
    """
    from src.domains.intelligence.proposal_service import (  # noqa: PLC0415
        ACTION_RECONCILIATION_MATCH,
        ProposalService,
    )

    for match in matches:
        if await _pending_reconciliation_proposal_exists(session, match.transaction_id):
            continue
        occurred_at = occurred_at_by_txn.get(match.transaction_id) or datetime.now(UTC)
        payload = match.model_dump()
        payload["occurred_at"] = occurred_at.isoformat()
        await ProposalService(session).create_proposal(
            agent_label="c_reconciler",
            action_type=ACTION_RECONCILIATION_MATCH,
            payload=payload,
            triggered_by=None,
            rationale=(
                f"{match.match_type} match (score {match.match_score:.2f}): "
                f"transaction {match.transaction_id} → invoice {match.invoice_id}"
            ),
        )


# ---------------------------------------------------------------------------
# Core reconciliation pipeline — reused by the LangGraph node AND the Celery task
# ---------------------------------------------------------------------------

async def run_reconciliation(session: AsyncSession) -> ReconciliationReport:
    """
    Execute one batch of the two-pass reconciliation pipeline.

    Fetches unreconciled M-Pesa transactions and open invoices with
    FOR UPDATE SKIP LOCKED to prevent concurrent duplicate processing, runs
    Pass 1 then Pass 2, applies Pass 1's exact matches, queues Pass 2's
    fuzzy/semantic matches for human review, and returns a ReconciliationReport
    with match statistics.

    Atomicity guarantee
    -------------------
    Data fetches and Pass 1's invoice/transaction writes run inside a single
    `session.begin()` transaction.  If any `apply_confirmed_match` call raises
    (e.g. a constraint violation on a specific invoice), the context manager
    issues an automatic ROLLBACK, undoing every write in the batch so the
    database is never left in a partial state.  FOR UPDATE SKIP LOCKED locks
    are also released on rollback, allowing the next poll cycle to retry.
    Pass 2 proposals are created afterward, outside that transaction (see
    `_propose_semantic_matches`).

    Callers (`agents.c_reconciler.make_c_reconciler_node` and the Celery batch
    task) must NOT call `session.commit()` after this function returns —
    `session.begin()` owns it.
    """
    run_at = datetime.now(UTC).isoformat()

    # Pick up runtime tuning overrides before the batch (own session — safe
    # alongside the caller's session.begin() below).
    await refresh_agent_tuning_from_db()
    _apply_reconciler_tuning()

    async with session.begin():
        # ── Fetch data with row-level locks ──────────────────────────────────
        txn_sql = text("""
            SELECT id::text, trans_id, amount::float, phone, bill_ref, created_at
            FROM mpesa_transactions
            WHERE is_reconciled = FALSE
            ORDER BY created_at ASC
            LIMIT :lim
            FOR UPDATE SKIP LOCKED
        """)
        txn_result = await session.execute(txn_sql, {"lim": _TXN_BATCH})
        transactions = [
            dict(zip(txn_result.keys(), row, strict=False))
            for row in txn_result.fetchall()
        ]

        inv_sql = text("""
            SELECT id::text, invoice_number, status::text, total::float,
                   amount_paid::float, balance_due::float, due_date, customer_id::text
            FROM invoices
            WHERE status IN ('SENT', 'OVERDUE')
              AND balance_due > 0
            ORDER BY due_date ASC NULLS LAST
            LIMIT :lim
            FOR UPDATE SKIP LOCKED
        """)
        inv_result = await session.execute(inv_sql, {"lim": _INV_LIMIT})
        invoices = [
            dict(zip(inv_result.keys(), row, strict=False))
            for row in inv_result.fetchall()
        ]

        # ── Pass 1 — deterministic ────────────────────────────────────────────
        if transactions and invoices:
            exact_matches, matched_txn_ids, matched_inv_ids = _pass1_exact(
                transactions, invoices
            )

            # ── Pass 2 — rapidfuzz + the model ───────────────────────────────────
            # _pass2_semantic catches the model errors internally and returns []
            # on failure, so a model outage never aborts the whole transaction.
            semantic_matches = await _pass2_semantic(
                transactions, invoices, matched_txn_ids, matched_inv_ids
            )
            for m in semantic_matches:
                matched_txn_ids.add(m.transaction_id)
                matched_inv_ids.add(m.invoice_id)

            all_matches = exact_matches + semantic_matches

            # ── Persist Pass 1 (deterministic) — all writes or none ────────────
            # Only exact matches auto-apply here. Pass 2 (fuzzy/semantic — an LLM
            # judgment call) is queued for human sign-off *after* this transaction
            # commits, not applied inline — see _propose_semantic_matches.
            # If apply_confirmed_match raises on any exact match, session.begin()
            # rolls back the entire batch automatically; no partial state commits.
            txn_dates = {t["id"]: t["created_at"] for t in transactions}
            for match in exact_matches:
                try:
                    await apply_confirmed_match(
                        session, match, txn_dates.get(match.transaction_id) or datetime.now(UTC)
                    )
                except Exception as exc:
                    # Log the offending invoice before re-raising so operators
                    # can identify the problematic record in structured logs
                    # without having to reconstruct it from a generic traceback.
                    logger.error(
                        "reconciliation_service: apply_confirmed_match failed — "
                        "rolling back entire batch",
                        invoice_id=match.invoice_id,
                        transaction_id=match.transaction_id,
                        match_type=match.match_type,
                        match_score=match.match_score,
                        error=str(exc),
                        exc_info=True,
                    )
                    raise  # propagates to session.begin() → full batch ROLLBACK
        else:
            exact_matches = []
            matched_txn_ids = set()
            all_matches = []
            semantic_matches = []
            txn_dates = {}

        # session.begin() commits here on clean exit.

    # Queue Pass 2 matches for review outside the Pass 1 transaction —
    # ProposalService.create_proposal owns its own commit and must not be
    # nested inside session.begin() above.
    if semantic_matches:
        await _propose_semantic_matches(session, semantic_matches, txn_dates)

    fuzzy_count = sum(1 for m in all_matches if m.match_type != "exact")
    report = ReconciliationReport(
        total_transactions=len(transactions),
        matched_exact=len(exact_matches),
        matched_fuzzy=fuzzy_count,
        proposed_for_review=len(semantic_matches),
        unmatched=len(transactions) - len(matched_txn_ids),
        matches=all_matches,
        run_at=run_at,
    )
    logger.info(
        "reconciliation_service: run complete",
        total=report.total_transactions,
        exact=report.matched_exact,
        fuzzy=report.matched_fuzzy,
        proposed_for_review=report.proposed_for_review,
        unmatched=report.unmatched,
    )
    return report


# ---------------------------------------------------------------------------
# Bank statement reconciliation — bank_statement_lines → invoices
# ---------------------------------------------------------------------------

async def run_bank_reconciliation(session: AsyncSession) -> ReconciliationReport:
    """Reconcile imported bank statement lines against open invoices.

    Mirrors :func:`run_reconciliation` but reads ``bank_statement_lines`` instead
    of ``mpesa_transactions``.  Each line is mapped to the same dict shape the
    two-pass matchers already consume (``reference_text`` → ``bill_ref``, ``date``
    → ``created_at``, no phone), so ``_pass1_exact`` / ``_pass2_semantic`` are
    reused unchanged.  Pass 1 matches are persisted via the shared event-sourced
    ``apply_confirmed_match`` with ``source="bank"`` → ``Payment(vault=BANK)``;
    Pass 2 matches are queued for review exactly like ``run_reconciliation``.
    Same single-transaction atomicity and ``FOR UPDATE SKIP LOCKED`` guarantees.
    """
    run_at = datetime.now(UTC).isoformat()

    # Pick up runtime tuning overrides before the batch (own session — safe
    # alongside the caller's session.begin() below).
    await refresh_agent_tuning_from_db()
    _apply_reconciler_tuning()

    async with session.begin():
        # Maker-checker: only APPROVED lines are eligible — a reviewer (≠ importer)
        # must release a line before it can settle invoices.
        line_sql = text("""
            SELECT id::text, amount::float, reference_text, date
            FROM bank_statement_lines
            WHERE is_reconciled = FALSE
              AND review_status = 'approved'
            ORDER BY date ASC
            LIMIT :lim
            FOR UPDATE SKIP LOCKED
        """)
        line_result = await session.execute(line_sql, {"lim": _TXN_BATCH})
        # Adapt bank lines to the transaction dict shape the matchers expect.
        transactions = [
            {
                "id": row[0],
                "amount": row[1],
                "bill_ref": row[2],
                "created_at": row[3],
                "phone": "",
            }
            for row in line_result.fetchall()
        ]

        inv_sql = text("""
            SELECT id::text, invoice_number, status::text, total::float,
                   amount_paid::float, balance_due::float, due_date, customer_id::text
            FROM invoices
            WHERE status IN ('SENT', 'OVERDUE')
              AND balance_due > 0
            ORDER BY due_date ASC NULLS LAST
            LIMIT :lim
            FOR UPDATE SKIP LOCKED
        """)
        inv_result = await session.execute(inv_sql, {"lim": _INV_LIMIT})
        invoices = [
            dict(zip(inv_result.keys(), row, strict=False))
            for row in inv_result.fetchall()
        ]

        if transactions and invoices:
            exact_matches, matched_txn_ids, matched_inv_ids = _pass1_exact(
                transactions, invoices
            )
            semantic_matches = await _pass2_semantic(
                transactions, invoices, matched_txn_ids, matched_inv_ids
            )
            for m in semantic_matches:
                matched_txn_ids.add(m.transaction_id)
                matched_inv_ids.add(m.invoice_id)

            all_matches = exact_matches + semantic_matches
            # Tag every match so apply_confirmed_match records Payment(vault=BANK).
            for m in all_matches:
                m.source = "bank"

            # ── Persist Pass 1 (deterministic) — all writes or none ────────────
            # Pass 2 (fuzzy/semantic) is queued for human sign-off after this
            # transaction commits, not applied inline — see run_reconciliation's
            # matching comment and _propose_semantic_matches.
            line_dates = {t["id"]: t["created_at"] for t in transactions}
            for match in exact_matches:
                try:
                    await apply_confirmed_match(
                        session, match, line_dates.get(match.transaction_id) or datetime.now(UTC)
                    )
                except Exception as exc:
                    logger.error(
                        "reconciliation_service: bank apply_confirmed_match failed — "
                        "rolling back entire batch",
                        invoice_id=match.invoice_id,
                        bank_line_id=match.transaction_id,
                        match_type=match.match_type,
                        match_score=match.match_score,
                        error=str(exc),
                        exc_info=True,
                    )
                    raise
        else:
            exact_matches = []
            matched_txn_ids = set()
            all_matches = []
            semantic_matches = []
            line_dates = {}

    if semantic_matches:
        await _propose_semantic_matches(session, semantic_matches, line_dates)

    fuzzy_count = sum(1 for m in all_matches if m.match_type != "exact")
    report = ReconciliationReport(
        total_transactions=len(transactions),
        matched_exact=len(exact_matches),
        matched_fuzzy=fuzzy_count,
        proposed_for_review=len(semantic_matches),
        unmatched=len(transactions) - len(matched_txn_ids),
        matches=all_matches,
        run_at=run_at,
    )
    logger.info(
        "reconciliation_service: bank run complete",
        total=report.total_transactions,
        exact=report.matched_exact,
        fuzzy=report.matched_fuzzy,
        proposed_for_review=report.proposed_for_review,
        unmatched=report.unmatched,
    )
    return report
