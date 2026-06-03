"""
Read-only SQL executor tool.

Restricted to SELECT statements; rejects any DDL or DML at the string level
before the query ever reaches the database engine.

For Text-to-SQL (Agent D CoVe), prefer make_readonly_sql_executor() which
binds to the finguard_readonly PostgreSQL role for defence-in-depth.

Sprint 6 — Schema Masking:
  get_masked_schema(agent_id) returns DDL only for the tables an agent is
  permitted to see, preventing LLM hallucination over sensitive tables
  (users, knowledge_base, outbox_events).
"""
from __future__ import annotations

import re
from typing import Any

from langchain_core.tools import tool
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.database.postgres import ReadOnlyAsyncSessionLocal

_FORBIDDEN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|TRUNCATE|ALTER|CREATE|REPLACE|MERGE|EXEC|EXECUTE|CALL)\b",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Per-table DDL fragments (read-only description for LLM context injection)
# ---------------------------------------------------------------------------

_TABLE_DDL: dict[str, str] = {
    "ledger_entries": """\
ledger_entries(
    id              UUID PRIMARY KEY,
    account_id      UUID,
    customer_id     UUID,
    transaction_type TEXT,        -- 'debit' | 'credit'
    amount          NUMERIC,
    currency        TEXT,
    description     TEXT,
    category        TEXT,
    reference       TEXT,
    created_at      TIMESTAMPTZ
)""",
    "invoices": """\
invoices(
    id              UUID PRIMARY KEY,
    customer_id     UUID,
    invoice_number  TEXT,
    status          TEXT,         -- 'draft'|'sent'|'paid'|'partially_paid'|'overdue'|'cancelled'
    subtotal        NUMERIC,
    tax             NUMERIC,
    total           NUMERIC,
    amount_paid     NUMERIC,
    balance_due     NUMERIC,
    currency        TEXT,
    due_date        TIMESTAMPTZ,
    created_at      TIMESTAMPTZ
)""",
    "budgets": """\
budgets(
    id              UUID PRIMARY KEY,
    name            TEXT,
    category        TEXT,
    amount          NUMERIC,
    spent           NUMERIC,
    currency        TEXT,
    period_start    TIMESTAMPTZ,
    period_end      TIMESTAMPTZ,
    created_at      TIMESTAMPTZ
)""",
    "expenses": """\
expenses(
    id              UUID PRIMARY KEY,
    expense_ref     TEXT,
    customer_id     UUID,
    category        TEXT,
    amount          NUMERIC,
    vault           TEXT,
    mpesa_trans_id  UUID,
    invoice_id      UUID,
    created_at      TIMESTAMPTZ
)""",
    "mpesa_transactions": """\
mpesa_transactions(
    id              UUID PRIMARY KEY,
    trans_id        TEXT,
    amount          NUMERIC,
    phone           TEXT,
    bill_ref        TEXT,
    is_reconciled   BOOLEAN,
    created_at      TIMESTAMPTZ
)""",
}

# Agent D (d_forecaster / IntelliAgent) is the only consumer of Text-to-SQL.
# It must NEVER see users, knowledge_base, or outbox_events.
_AGENT_ALLOWED_TABLES: dict[str, frozenset[str]] = {
    "D": frozenset({"ledger_entries", "invoices", "budgets", "expenses"}),
    # Other agents do not use dynamic SQL; add entries here as needed.
}


def get_masked_schema(agent_id: str) -> str:
    """
    Return a DDL string containing only the tables the agent is authorised to query.

    Agent D receives ledger_entries, invoices, budgets, and expenses.
    Sensitive tables (users, knowledge_base, outbox_events) are never included.

    Raises KeyError for unknown agent IDs.
    """
    allowed = _AGENT_ALLOWED_TABLES[agent_id]
    fragments = [_TABLE_DDL[t] for t in sorted(allowed) if t in _TABLE_DDL]
    return "\n\n".join(fragments)


def _validate(query: str) -> None:
    stripped = query.strip()
    if not stripped.upper().startswith("SELECT"):
        raise ValueError("Only SELECT queries are permitted")
    if _FORBIDDEN.search(stripped):
        raise ValueError("Query contains forbidden keyword")


def make_sql_executor(session: AsyncSession) -> Any:
    @tool
    async def execute_sql(query: str) -> list[dict[str, Any]]:
        """Run a read-only SELECT query against the Finguard PostgreSQL database.

        Args:
            query: A plain SQL SELECT statement. No parameters — embed literal
                   values directly. Maximum 1000 rows returned.
        """
        _validate(query)
        result = await session.execute(text(query))
        keys = list(result.keys())
        rows = result.fetchmany(1000)
        return [dict(zip(keys, row, strict=False)) for row in rows]

    return execute_sql


async def execute_readonly_sql(query: str) -> list[dict[str, Any]]:
    """
    Execute a validated SELECT query using the read-only session factory.

    Used by the Text-to-SQL CoVe workflow in Agent D so LLM-generated queries
    run under the finguard_readonly PostgreSQL role, even if DATABASE_READONLY_URL
    is not yet configured (falls back gracefully to the main engine).
    """
    _validate(query)
    async with ReadOnlyAsyncSessionLocal() as session:
        result = await session.execute(text(query))
        keys = list(result.keys())
        rows = result.fetchmany(1000)
        return [dict(zip(keys, row, strict=False)) for row in rows]
