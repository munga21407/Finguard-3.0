"""
Agent C — Reconciliation Detective.

Matches floating M-Pesa mobile money payments to open business invoices using a
two-pass algorithm:

  Pass 1 (Deterministic): Exact match on amount (±KES 1), date (±2 days), and
      reference substring — no LLM required.

  Pass 2 (Semantic): For residual unmatched transactions, rapidfuzz pre-filters
      candidates (token-sort ratio ≥ 65) which are then scored by Gemini to
      confirm or reject each pairing based on reference semantics, amounts, and
      phone-number identity signals.

Matched invoices are updated to "paid" or "partially_paid" with a row-level
FOR UPDATE lock to prevent race conditions from concurrent webhook events.

Writes context["reconciliation_report"] before returning to the Supervisor.
The core async function `run_reconciliation()` is also called directly by the
`run_batch_reconciliation` Celery task in batch.py.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import structlog
from langchain_core.messages import AIMessage
from rapidfuzz import fuzz
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.domains.intelligence.llm_client import generate_structured_content
from src.domains.intelligence.prompts.c_reconciler import RECONCILER_PASS2_SYSTEM
from src.domains.intelligence.schemas import (
    OrchestratorState,
    ReconciliationCandidate,
    ReconciliationMatch,
    ReconciliationReport,
    ReconciliationScoringResult,
)
from src.infrastructure.database.postgres import AsyncSessionLocal

logger = structlog.get_logger(__name__)

_TXN_BATCH = 100        # M-Pesa transactions per reconciliation run
_INV_LIMIT = 500        # Max open invoices to load
_FUZZY_THRESHOLD = 65   # rapidfuzz token_sort_ratio minimum for Pass 2 candidacy
_SEMANTIC_THRESHOLD = 0.60  # Gemini match_score minimum to confirm a match


# ---------------------------------------------------------------------------
# Matching helpers
# ---------------------------------------------------------------------------

def _amount_match(paid: float, due: float, tolerance: float = 1.0) -> bool:
    return abs(paid - due) <= tolerance


def _date_match(txn_date: Any, due_date: Any, window_days: int = 2) -> bool:
    if due_date is None:
        return True
    try:
        if hasattr(txn_date, "date"):
            t = txn_date.date()
        else:
            t = datetime.fromisoformat(str(txn_date)).date()
        if hasattr(due_date, "date"):
            d = due_date.date()
        else:
            d = datetime.fromisoformat(str(due_date)).date()
        return abs((t - d).days) <= window_days
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

def _pass1_exact(
    transactions: list[dict[str, Any]],
    invoices: list[dict[str, Any]],
) -> tuple[list[ReconciliationMatch], set[str], set[str]]:
    matched_txn_ids: set[str] = set()
    matched_inv_ids: set[str] = set()
    matches: list[ReconciliationMatch] = []

    for txn in transactions:
        for inv in invoices:
            if inv["id"] in matched_inv_ids:
                continue
            if not _amount_match(txn["amount"], inv["balance_due"]):
                continue
            if not _date_match(txn["created_at"], inv["due_date"]):
                continue
            if not _ref_match(txn.get("bill_ref"), inv["invoice_number"]):
                continue

            status = (
                "paid"
                if txn["amount"] >= inv["balance_due"] - 0.01
                else "partially_paid"
            )
            matches.append(
                ReconciliationMatch(
                    transaction_id=txn["id"],
                    invoice_id=inv["id"],
                    match_type="exact",
                    match_score=1.0,
                    amount=txn["amount"],
                    new_invoice_status=status,
                )
            )
            matched_txn_ids.add(txn["id"])
            matched_inv_ids.add(inv["id"])
            break

    return matches, matched_txn_ids, matched_inv_ids


# ---------------------------------------------------------------------------
# Pass 2 — rapidfuzz + Gemini semantic matching
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


async def _gemini_score_candidates(
    candidates: list[dict[str, Any]],
) -> ReconciliationScoringResult:
    prompt = (
        f"{RECONCILER_PASS2_SYSTEM}\n\n"
        "## Candidate Matches (JSON)\n"
        f"{json.dumps(candidates[:50], indent=2)}\n\n"
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
        scored = await _gemini_score_candidates(candidates)
    except Exception as exc:
        logger.error("c_reconciler: Gemini Pass 2 scoring failed", error=str(exc))
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
        # rapidfuzz-only matches score ≥ 0.9; Gemini-confirmed lower scores are "semantic"
        match_type = "fuzzy" if cand.match_score >= 0.90 else "semantic"
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

async def _apply_match(session: AsyncSession, match: ReconciliationMatch) -> None:
    update_inv = text("""
        UPDATE invoices
        SET
            status          = :status,
            amount_paid     = LEAST(amount_paid + :payment, total),
            balance_due     = GREATEST(balance_due - :payment, 0),
            paid_at         = CASE WHEN :status = 'paid' THEN NOW() AT TIME ZONE 'UTC'
                                   ELSE paid_at END,
            updated_at      = NOW() AT TIME ZONE 'UTC'
        WHERE id = :invoice_id::uuid
    """)
    await session.execute(
        update_inv,
        {
            "status": match.new_invoice_status,
            "payment": match.amount,
            "invoice_id": match.invoice_id,
        },
    )

    update_txn = text("""
        UPDATE mpesa_transactions
        SET is_reconciled = TRUE
        WHERE id = :txn_id::uuid
    """)
    await session.execute(update_txn, {"txn_id": match.transaction_id})


# ---------------------------------------------------------------------------
# Core reconciliation pipeline — reused by the LangGraph node AND the Celery task
# ---------------------------------------------------------------------------

async def run_reconciliation(session: AsyncSession) -> ReconciliationReport:
    """
    Execute one batch of the two-pass reconciliation pipeline.

    Fetches unreconciled M-Pesa transactions and open invoices with
    FOR UPDATE SKIP LOCKED to prevent concurrent duplicate processing,
    runs Pass 1 then Pass 2, persists all confirmed matches, and returns
    a ReconciliationReport with match statistics.

    Atomicity guarantee
    -------------------
    The entire function — both data fetches and all invoice/transaction writes —
    runs inside a single `session.begin()` transaction.  If any `_apply_match`
    call raises (e.g. a constraint violation on a specific invoice), the context
    manager issues an automatic ROLLBACK, undoing every write in the batch so
    the database is never left in a partial state.  FOR UPDATE SKIP LOCKED
    locks are also released on rollback, allowing the next poll cycle to retry.

    Callers (`make_c_reconciler_node` and the Celery batch task) must NOT call
    `session.commit()` after this function returns — `session.begin()` owns it.
    """
    run_at = datetime.now(UTC).isoformat()

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
            WHERE status IN ('sent', 'overdue')
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

            # ── Pass 2 — rapidfuzz + Gemini ───────────────────────────────────
            # _pass2_semantic catches Gemini errors internally and returns []
            # on failure, so a Gemini outage never aborts the whole transaction.
            semantic_matches = await _pass2_semantic(
                transactions, invoices, matched_txn_ids, matched_inv_ids
            )
            for m in semantic_matches:
                matched_txn_ids.add(m.transaction_id)
                matched_inv_ids.add(m.invoice_id)

            all_matches = exact_matches + semantic_matches

            # ── Persist — all writes or none ──────────────────────────────────
            # If _apply_match raises on any single match, session.begin() rolls
            # back the entire batch automatically; no partial state is committed.
            for match in all_matches:
                try:
                    await _apply_match(session, match)
                except Exception as exc:
                    # Log the offending invoice before re-raising so operators
                    # can identify the problematic record in structured logs
                    # without having to reconstruct it from a generic traceback.
                    logger.error(
                        "c_reconciler: _apply_match failed — rolling back entire batch",
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

        # session.begin() commits here on clean exit.

    fuzzy_count = sum(1 for m in all_matches if m.match_type != "exact")
    report = ReconciliationReport(
        total_transactions=len(transactions),
        matched_exact=len(exact_matches),
        matched_fuzzy=fuzzy_count,
        unmatched=len(transactions) - len(matched_txn_ids),
        matches=all_matches,
        run_at=run_at,
    )
    logger.info(
        "c_reconciler: run complete",
        total=report.total_transactions,
        exact=report.matched_exact,
        fuzzy=report.matched_fuzzy,
        unmatched=report.unmatched,
    )
    return report


# ---------------------------------------------------------------------------
# LangGraph node
# ---------------------------------------------------------------------------

def make_c_reconciler_node(llm: Any = None) -> Any:  # llm kept for signature compatibility
    async def c_reconciler_node(state: OrchestratorState) -> dict[str, Any]:
        async with AsyncSessionLocal() as session:
            try:
                report = await run_reconciliation(session)
            except Exception as exc:
                logger.error("c_reconciler: reconciliation failed", error=str(exc))
                return {
                    "messages": [
                        AIMessage(
                            content=f"[c_reconciler] Reconciliation failed: {exc}",
                            name="c_reconciler",
                        )
                    ],
                    "context": state["context"],
                }

        updated_ctx = dict(state["context"])
        updated_ctx["reconciliation_report"] = report.model_dump()

        summary = (
            f"[c_reconciler] Reconciliation complete — "
            f"{report.total_transactions} transactions processed: "
            f"{report.matched_exact} exact, {report.matched_fuzzy} semantic, "
            f"{report.unmatched} unmatched."
        )

        return {
            "messages": [AIMessage(content=summary, name="c_reconciler")],
            "context": updated_ctx,
        }

    return c_reconciler_node
