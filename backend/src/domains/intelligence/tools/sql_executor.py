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

import sqlglot
import structlog
from langchain_core.tools import tool
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlglot import exp
from sqlglot.errors import ParseError

from src.core.config import settings
from src.infrastructure.database.postgres import ReadOnlyAsyncSessionLocal

logger = structlog.get_logger(__name__)

# First-pass: fast regex pre-filter catches obvious keyword injection before
# paying the cost of a full parse.  The AST check below is the authoritative
# gate — this just short-circuits clearly invalid inputs early.
_FORBIDDEN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|TRUNCATE|ALTER|CREATE|REPLACE|MERGE|EXEC|EXECUTE|CALL)\b",
    re.IGNORECASE,
)

# Every AST node type that represents a non-read-only operation.
# exp.Command catches unknown DDL statements that sqlglot cannot fully model.
_FORBIDDEN_NODE_TYPES = (
    exp.Drop,
    exp.Delete,
    exp.Update,
    exp.Insert,
    exp.Alter,
    exp.Create,
    exp.TruncateTable,
    exp.Command,
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


def _ast_validate(query: str) -> None:
    """
    Deterministic SQL AST validation via sqlglot.

    Two-stage defence:
      1. Parse the full input with ``sqlglot.parse()`` and reject multi-statement
         inputs (e.g. ``SELECT 1; DROP TABLE users``).
      2. Parse with ``sqlglot.parse_one()`` and walk the AST to confirm the root
         is a ``Select`` and that no DML/DDL node exists anywhere in the tree —
         preventing subquery-injection bypasses that fool simple regex checks.

    Raises:
        ValueError — on parse failure, multi-statement input, non-SELECT root,
            or any forbidden node found in the AST.  The message is forwarded
            directly to the LangGraph node so Explainer/Auditor agents can retry.
    """
    # ── Stage 1: multi-statement injection guard ─────────────────────────
    try:
        all_stmts = sqlglot.parse(query, dialect="postgres")
    except ParseError as exc:
        raise ValueError(
            f"SQL parse error — LLM-generated query has invalid syntax: {exc}"
        ) from exc

    non_empty = [s for s in all_stmts if s is not None]
    if len(non_empty) > 1:
        raise ValueError(
            f"Only a single SELECT statement is permitted; "
            f"got {len(non_empty)} statement(s) — possible injection attempt"
        )

    # ── Stage 2: AST root + forbidden-node walk ──────────────────────────
    try:
        tree = sqlglot.parse_one(query, dialect="postgres")
    except ParseError as exc:
        raise ValueError(
            f"SQL parse error — LLM-generated query has invalid syntax: {exc}"
        ) from exc

    if tree is None:
        raise ValueError("SQL parse returned an empty AST")

    if not isinstance(tree, exp.Select):
        raise ValueError(
            f"Only SELECT statements are permitted; "
            f"got {type(tree).__name__} — possible injection attempt"
        )

    forbidden_node = next(tree.find_all(*_FORBIDDEN_NODE_TYPES), None)
    if forbidden_node is not None:
        raise ValueError(
            f"Forbidden SQL operation '{type(forbidden_node).__name__}' "
            f"detected in query AST — query rejected"
        )


def _validate(query: str) -> None:
    """
    Two-layer read-only guard:
      1. Regex pre-filter — fast rejection of obvious forbidden keywords.
      2. sqlglot AST validation — deterministic, bypass-proof structural check.
    """
    stripped = query.strip()
    if not stripped.upper().startswith("SELECT"):
        raise ValueError("Only SELECT queries are permitted")
    if _FORBIDDEN.search(stripped):
        raise ValueError("Query contains forbidden keyword")
    # AST check is the authoritative gate — runs even when the regex passes,
    # catching obfuscation techniques that survive keyword scanning.
    _ast_validate(stripped)


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

    if not settings.DATABASE_READONLY_URL:
        logger.warning(
            "sql_executor: DATABASE_READONLY_URL is not configured — "
            "LLM-generated SQL is executing against the fully-privileged main "
            "database engine. This violates the read-only role security boundary. "
            "Run infrastructure/db_security.sql and set DATABASE_READONLY_URL "
            "to enforce defence-in-depth for Agent D CoVe queries.",
            query_preview=query[:120],
        )

    async with ReadOnlyAsyncSessionLocal() as session:
        result = await session.execute(text(query))
        keys = list(result.keys())
        rows = result.fetchmany(1000)
        return [dict(zip(keys, row, strict=False)) for row in rows]
