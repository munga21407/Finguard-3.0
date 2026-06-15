"""Read-only SQL guard: CTEs are permitted, DML/DDL is rejected everywhere.

The string-level leading-keyword check now allows ``WITH`` (CTEs) in addition
to ``SELECT``; the sqlglot AST walk remains the authoritative gate. These tests
pin both halves so loosening the keyword filter can never silently let a write
through (e.g. a DML hidden inside a CTE body).
"""
from __future__ import annotations

import pytest

from src.domains.intelligence.tools.sql_executor import _enforce_limit, _validate


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
