"""Phase 3 (DeepSeek-harness-inspired roadmap) — generalized tool-capability
registry: agent_registry.TOOL_GRANTS / allowed_sql_tables / allowed_http_hosts
/ allowed_event_exchanges.

Pure unit tests over the declarative table — no DB/Mongo/network needed.
"""
from __future__ import annotations

from src.domains.intelligence.agent_registry import (
    allowed_event_exchanges,
    allowed_http_hosts,
    allowed_sql_tables,
)


def test_d_sql_grant() -> None:
    assert allowed_sql_tables("D") == {
        "ledger_entries", "invoices", "budgets", "expenses",
    }


def test_k_sql_grant() -> None:
    assert allowed_sql_tables("K") == {"products", "stock_levels", "stock_movements"}


def test_e_sql_grant_is_narrower_than_d_and_k() -> None:
    """E only ever queries ledger_entries/invoices (see e_watchdog.py's
    _fetch_recent_amounts/_fetch_recent_invoices) — its grant must not include
    D's or K's other tables, closing the gap the old global table-union
    enforcement previously left open."""
    e_tables = allowed_sql_tables("E")
    assert e_tables == {"ledger_entries", "invoices"}
    assert "budgets" not in e_tables
    assert "expenses" not in e_tables
    assert "products" not in e_tables
    assert "stock_levels" not in e_tables
    assert "stock_movements" not in e_tables


def test_e_event_grant_is_narrower_than_the_global_allowlist() -> None:
    assert allowed_event_exchanges("E") == {"finguard.intelligence"}


def test_i_http_grant() -> None:
    hosts = allowed_http_hosts("I")
    assert hosts == {
        "sandbox.safaricom.co.ke",
        "api.metropol.co.ke",
        "itax.kra.go.ke",
        "open.er-api.com",  # hostname of settings.FX_API_URL's default
    }


def test_unknown_agent_gets_no_grants_fail_closed() -> None:
    assert allowed_sql_tables("ZZ") == frozenset()
    assert allowed_http_hosts("ZZ") == frozenset()
    assert allowed_event_exchanges("ZZ") == frozenset()


def test_grants_are_isolated_across_agents() -> None:
    """K has no http/events grant, D has no http/events grant, E has no http
    grant — an agent's tool-set is exactly what's declared, nothing implicit."""
    assert allowed_http_hosts("D") == frozenset()
    assert allowed_http_hosts("K") == frozenset()
    assert allowed_http_hosts("E") == frozenset()
    assert allowed_event_exchanges("D") == frozenset()
    assert allowed_event_exchanges("K") == frozenset()
    assert allowed_sql_tables("I") == frozenset()
