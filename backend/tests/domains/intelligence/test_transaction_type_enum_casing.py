"""Regression guard: the ``transactiontype`` ENUM casing contract.

SQLAlchemy's ``Enum(TransactionType)`` persists the enum member *NAMES*
('DEBIT', 'CREDIT'), not the lowercase ``.value``s — so the Postgres enum only
accepts uppercase. Raw SQL (and the Text-to-SQL LLM) using lowercase 'credit' /
'debit' raises ``InvalidTextRepresentationError`` at runtime and breaks reports.

These tests pin the contract so the whole class of bug cannot silently return:
  1. the labels we advertise match what SQLAlchemy actually binds/creates;
  2. the schema we hand the LLM shows the exact uppercase labels;
  3. no source file compares ``transaction_type`` against a lowercase literal.
"""
from __future__ import annotations

import re
from pathlib import Path

from sqlalchemy import Enum as SAEnum

from src.domains.finance.models import TransactionType
from src.domains.intelligence.tools.sql_executor import (
    TRANSACTION_TYPE_LABELS,
    fetch_pg_enum_labels,
    get_masked_schema,
)

_SRC_ROOT = Path(__file__).resolve().parents[3] / "src"
# Matches ONLY a lowercase literal — `transaction_type = 'credit'` /
# `le.transaction_type = 'debit'`. Case-sensitive on purpose: the correct
# uppercase 'CREDIT'/'DEBIT' comparisons must NOT be flagged.
_LOWERCASE_ENUM_CMP = re.compile(r"transaction_type\s*=\s*'(credit|debit)'")


def test_labels_match_sqlalchemy_persisted_values() -> None:
    """The advertised labels must equal what SQLAlchemy actually sends to Postgres."""
    sa_enum = SAEnum(TransactionType)
    persisted = {sa_enum._db_value_for_elem(m) for m in TransactionType}
    assert set(TRANSACTION_TYPE_LABELS) == persisted == {"DEBIT", "CREDIT"}
    # And they are the NAMES, not the lowercase values — the crux of the bug.
    assert tuple(m.name for m in TransactionType) == TRANSACTION_TYPE_LABELS
    assert "credit" not in TRANSACTION_TYPE_LABELS


def test_masked_schema_advertises_exact_uppercase_labels() -> None:
    schema = get_masked_schema("D")
    assert "'CREDIT'" in schema and "'DEBIT'" in schema
    # The old, wrong lowercase hint must never come back.
    assert "'credit'" not in schema and "'debit'" not in schema


def test_inventory_schema_hints_use_uppercase_enum_names() -> None:
    """Agent K's tables are native_enum=False but still store NAMES — hints must
    advertise the uppercase names, not the lowercase values."""
    schema = get_masked_schema("K")
    assert "'SALE'" in schema and "'RECEIPT'" in schema and "'KG'" in schema
    # The old lowercase hints (`receipt|issue|sale`, `each|kg`) must not return.
    assert "each|kg" not in schema
    assert "receipt|issue|sale" not in schema


def test_no_lowercase_enum_comparisons_in_source() -> None:
    """Fail loudly if any raw SQL reintroduces a lowercase enum comparison."""
    offenders: list[str] = []
    for path in _SRC_ROOT.rglob("*.py"):
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if _LOWERCASE_ENUM_CMP.search(line):
                offenders.append(f"{path.relative_to(_SRC_ROOT)}:{lineno}: {line.strip()}")
    assert not offenders, (
        "Lowercase transaction_type enum comparisons found (Postgres wants "
        "'CREDIT'/'DEBIT'):\n" + "\n".join(offenders)
    )


def test_fetch_pg_enum_labels_is_awaitable() -> None:
    """Smoke: the introspection helper exists and is coroutine-shaped (no DB needed)."""
    import inspect

    assert inspect.iscoroutinefunction(fetch_pg_enum_labels)
