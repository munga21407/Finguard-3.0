"""Read-only SQL guard: CTEs are permitted, DML/DDL is rejected everywhere.

The string-level leading-keyword check now allows ``WITH`` (CTEs) in addition
to ``SELECT``; the sqlglot AST walk remains the authoritative gate. These tests
pin both halves so loosening the keyword filter can never silently let a write
through (e.g. a DML hidden inside a CTE body).
"""
from __future__ import annotations

import pytest

from src.domains.intelligence.tools.sql_executor import (
    _READONLY_ALLOWED_TABLES,
    _enforce_limit,
    _validate,
)


def test_plain_select_allowed() -> None:
    _validate("SELECT id, total FROM invoices WHERE status = 'paid'")


def test_cte_select_allowed() -> None:
    # Regression: WITH … SELECT must pass — Agent D forecasting relies on CTEs.
    _validate(
        "WITH paid AS (SELECT total FROM invoices WHERE status = 'paid') "
        "SELECT SUM(total) FROM paid"
    )


def test_cte_wrapping_delete_rejected() -> None:
    # The dangerous case: a CTE body that performs a write must be blocked by the
    # AST forbidden-node walk even though the statement starts with WITH.
    with pytest.raises(ValueError):
        _validate(
            "WITH x AS (DELETE FROM users RETURNING id) SELECT id FROM x"
        )


def test_cte_wrapping_insert_rejected() -> None:
    with pytest.raises(ValueError):
        _validate(
            "WITH x AS (INSERT INTO ledger_entries (id) VALUES (gen_random_uuid()) "
            "RETURNING id) SELECT id FROM x"
        )


@pytest.mark.parametrize(
    "query",
    [
        "DELETE FROM invoices",
        "UPDATE invoices SET total = 0",
        "DROP TABLE users",
        "SELECT 1; DROP TABLE users",
    ],
)
def test_forbidden_statements_rejected(query: str) -> None:
    with pytest.raises(ValueError):
        _validate(query)


def test_cte_limit_enforced() -> None:
    # _enforce_limit must clamp a CTE query (root is still a Select) to 100 rows.
    out = _enforce_limit(
        "WITH x AS (SELECT total FROM invoices) SELECT * FROM x LIMIT 5000"
    )
    assert "LIMIT 100" in out.upper()


# ── Table allowlist (structural schema masking) ─────────────────────────────────


def test_allowed_table_select_passes() -> None:
    # Tables in the read-only allowlist are permitted.
    _validate(
        "SELECT id, total FROM invoices", allowed_tables=_READONLY_ALLOWED_TABLES
    )


@pytest.mark.parametrize(
    "query",
    [
        "SELECT hashed_password FROM users",                       # sensitive table
        "SELECT content FROM knowledge_base",                      # sensitive table
        "SELECT * FROM outbox_events",                             # sensitive table
        "SELECT * FROM information_schema.columns",                # catalog probe
        "SELECT * FROM pg_catalog.pg_user",                        # catalog probe
        "SELECT total FROM invoices UNION SELECT email FROM users",  # hidden join
        "SELECT i.total FROM invoices i JOIN users u ON u.id = i.customer_id",
    ],
)
def test_disallowed_table_rejected(query: str) -> None:
    # A perfectly valid read-only SELECT is still refused when it reaches outside
    # the allowlist — the gate that prompt-only schema masking cannot enforce.
    with pytest.raises(ValueError):
        _validate(query, allowed_tables=_READONLY_ALLOWED_TABLES)


def test_cte_name_not_treated_as_disallowed_table() -> None:
    # A CTE identifier is a derived name, not a physical table, so referencing it
    # must not trip the allowlist.
    _validate(
        "WITH paid AS (SELECT total FROM invoices WHERE status = 'paid') "
        "SELECT SUM(total) FROM paid",
        allowed_tables=_READONLY_ALLOWED_TABLES,
    )


def test_allowlist_not_enforced_without_set() -> None:
    # Back-compat: the generic validator (no allowlist) leaves table access open.
    _validate("SELECT email FROM users")
