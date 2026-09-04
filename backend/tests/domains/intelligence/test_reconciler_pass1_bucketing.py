"""Sprint 3 — Agent C Pass 1 amount-bucketing: same results, no O(n×m) scan.

The bucketed ``_pass1_exact`` must produce byte-identical matches to a brute-force
reference over the same data, including first-match determinism and floor-boundary
amounts.
"""
from __future__ import annotations

import random
from typing import Any

from src.domains.intelligence.services.reconciliation_service import (
    _amount_match,
    _date_match,
    _pass1_exact,
    _ref_match,
)


def _txn(tid: str, amount: float, ref: str, created: str = "2026-01-01") -> dict[str, Any]:
    return {"id": tid, "amount": amount, "bill_ref": ref, "created_at": created}


def _inv(iid: str, balance: float, number: str, due: str = "2026-01-01") -> dict[str, Any]:
    return {"id": iid, "balance_due": balance, "invoice_number": number, "due_date": due}


def _brute_force(
    transactions: list[dict[str, Any]], invoices: list[dict[str, Any]]
) -> list[tuple[str, str]]:
    """Reference: the original nested-loop first-match pairing."""
    matched_inv: set[str] = set()
    pairs: list[tuple[str, str]] = []
    for t in transactions:
        for inv in invoices:
            if inv["id"] in matched_inv:
                continue
            if (
                _amount_match(t["amount"], inv["balance_due"])
                and _date_match(t["created_at"], inv["due_date"])
                and _ref_match(t.get("bill_ref"), inv["invoice_number"])
            ):
                pairs.append((t["id"], inv["id"]))
                matched_inv.add(inv["id"])
                break
    return pairs


def _pairs(matches: list[Any]) -> list[tuple[str, str]]:
    return [(m.transaction_id, m.invoice_id) for m in matches]


def test_floor_boundary_amounts_match() -> None:
    # balance 100.5 and 99.5 are both within ±1 of a 100.0 payment.
    matches, _, _ = _pass1_exact([_txn("t1", 100.0, "INV-1")], [_inv("i1", 100.5, "INV-1")])
    assert _pairs(matches) == [("t1", "i1")]
    matches, _, _ = _pass1_exact([_txn("t2", 100.0, "INV-2")], [_inv("i2", 99.5, "INV-2")])
    assert _pairs(matches) == [("t2", "i2")]


def test_amount_out_of_tolerance_no_match() -> None:
    matches, _, _ = _pass1_exact([_txn("t", 100.0, "INV-9")], [_inv("i", 105.0, "INV-9")])
    assert matches == []


def test_first_match_order_preserved() -> None:
    # Two invoices both fully match; the earlier-indexed one must win.
    invoices = [_inv("i_first", 50.0, "INV-7"), _inv("i_second", 50.0, "INV-7")]
    matches, _, _ = _pass1_exact([_txn("t", 50.0, "INV-7")], invoices)
    assert _pairs(matches) == [("t", "i_first")]


def test_bucketing_equals_bruteforce_random() -> None:
    rng = random.Random(42)
    invoices = [
        _inv(f"i{k}", round(rng.uniform(10, 500), 2), f"INV-{k % 30}")
        for k in range(120)
    ]
    transactions = [
        _txn(f"t{j}", round(rng.uniform(10, 500), 2), f"INV-{rng.randint(0, 29)}")
        for j in range(80)
    ]
    matches, _, _ = _pass1_exact(transactions, invoices)
    assert _pairs(matches) == _brute_force(transactions, invoices)
