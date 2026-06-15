"""Deterministic unit tests for Agent C (Reconciler) Pass-1 matching logic.

The exact-match predicates (_amount/_date/_ref) and the deterministic Pass-1
matcher run with no LLM/DB — only Pass-2 (rapidfuzz + Gemini) does. These pin
the exact-match contract: tolerance windows, reference matching, single-use of
each invoice, and paid-vs-partial status derivation.
"""
from __future__ import annotations

from datetime import datetime

from src.domains.intelligence.agents.c_reconciler import (
    _amount_match,
    _build_fuzzy_candidates,
    _date_match,
    _pass1_exact,
    _ref_match,
)

# ── predicates ────────────────────────────────────────────────────────────────

def test_amount_match_within_tolerance() -> None:
    assert _amount_match(100.0, 100.5) is True
    assert _amount_match(100.0, 102.0) is False


def test_date_match_window_and_null() -> None:
    assert _date_match("2026-01-01", None) is True           # no due date → pass
    assert _date_match("2026-01-01", "2026-01-02") is True    # within 2 days
    assert _date_match("2026-01-01", "2026-01-10") is False   # outside window
    assert _date_match("garbage", "2026-01-01") is True       # unparseable → defer


def test_ref_match_substring_and_tokens() -> None:
    assert _ref_match("INV-001", "INV-001") is True
    assert _ref_match("inv001", "Payment for INV001") is True  # substring, case-insensitive
    assert _ref_match(None, "INV-001") is False                # missing ref
    assert _ref_match("ZZZ", "INV-001") is False               # no overlap


# ── Pass 1 exact matcher ──────────────────────────────────────────────────────

def _txn(**kw: object) -> dict:
    base = {
        "id": "t1",
        "amount": 100.0,
        "created_at": datetime(2026, 1, 1),
        "bill_ref": "INV-001",
        "phone": "0700000000",
    }
    base.update(kw)
    return base


def _inv(**kw: object) -> dict:
    base = {
        "id": "i1",
        "balance_due": 100.0,
        "due_date": datetime(2026, 1, 1),
        "invoice_number": "INV-001",
    }
    base.update(kw)
    return base


def test_pass1_matches_exact_pair_as_paid() -> None:
    matches, m_txn, m_inv = _pass1_exact([_txn()], [_inv()])
    assert len(matches) == 1
    m = matches[0]
    assert (m.transaction_id, m.invoice_id, m.match_type) == ("t1", "i1", "exact")
    assert m.match_score == 1.0
    assert m.new_invoice_status == "paid"
    assert m_txn == {"t1"} and m_inv == {"i1"}


def test_pass1_partial_payment_status() -> None:
    matches, _, _ = _pass1_exact([_txn(amount=60.0)], [_inv(balance_due=60.5)])
    # amount (60) < balance_due (60.5) - 0.01 → partially_paid
    assert matches[0].new_invoice_status == "partially_paid"


def test_pass1_no_match_when_reference_differs() -> None:
    matches, m_txn, m_inv = _pass1_exact(
        [_txn(bill_ref="WRONG")], [_inv(invoice_number="INV-999")]
    )
    assert matches == []
    assert not m_txn and not m_inv


def test_pass1_each_invoice_matched_once() -> None:
    # Two identical transactions, one invoice → only the first claims it.
    txns = [_txn(id="t1"), _txn(id="t2")]
    matches, m_txn, m_inv = _pass1_exact(txns, [_inv()])
    assert len(matches) == 1
    assert m_inv == {"i1"}


# ── fuzzy candidate builder (Pass-2 input) ────────────────────────────────────

def test_fuzzy_candidates_skip_matched_and_require_bill_ref() -> None:
    txns = [
        _txn(id="t1", bill_ref="INV-001"),       # already matched → skipped
        _txn(id="t2", bill_ref=""),               # no bill_ref → skipped
        _txn(id="t3", bill_ref="INV-002"),        # eligible
    ]
    invs = [_inv(id="i1"), _inv(id="i2", invoice_number="INV-002")]
    candidates = _build_fuzzy_candidates(
        txns, invs, matched_txn_ids={"t1"}, matched_inv_ids={"i1"}
    )
    txn_ids = {c["transaction_id"] for c in candidates}
    assert "t1" not in txn_ids and "t2" not in txn_ids
    assert any(c["transaction_id"] == "t3" and c["invoice_id"] == "i2" for c in candidates)
