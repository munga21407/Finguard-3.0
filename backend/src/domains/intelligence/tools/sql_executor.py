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
from src.domains.finance.models import InvoiceStatus, TransactionType
from src.domains.intelligence.observability import traced_tool
from src.domains.inventory.types import MovementType, UnitOfMeasure
from src.infrastructure.database.postgres import ReadOnlyAsyncSessionLocal

logger = structlog.get_logger(__name__)

# ── Enum ground-truth ────────────────────────────────────────────────────────
# SQLAlchemy's ``Enum(TransactionType)`` persists the member *NAMES* (DEBIT,
# CREDIT), not the lowercase ``.value``s — so the Postgres ``transactiontype``
# type only accepts 'DEBIT'/'CREDIT'. Derive the exact labels from the enum
# itself (import-safe, no DB round-trip) so the schema we hand the LLM can never
# drift from what the database will actually accept. See fetch_pg_enum_labels()
# for the runtime cross-check against pg_enum.
TRANSACTION_TYPE_LABELS: tuple[str, ...] = tuple(m.name for m in TransactionType)
_TX_LABELS_SQL = " | ".join(f"'{label}'" for label in TRANSACTION_TYPE_LABELS)

# Same name-vs-value trap applies to invoices.status (invoicestatus ENUM).
INVOICE_STATUS_LABELS: tuple[str, ...] = tuple(m.name for m in InvoiceStatus)
_INVOICE_STATUS_SQL = " | ".join(f"'{label}'" for label in INVOICE_STATUS_LABELS)

# Inventory enums are ``native_enum=False`` (stored as VARCHAR), but SQLAlchemy
# STILL persists the member NAME — so 'sale'/'kg' silently match nothing. Same
# uppercase-name rule; derive the hints so they cannot drift from the enums.
_UNIT_SQL = " | ".join(f"'{m.name}'" for m in UnitOfMeasure)
_MOVEMENT_TYPE_SQL = " | ".join(f"'{m.name}'" for m in MovementType)


async def fetch_pg_enum_labels(session: AsyncSession, enum_type: str) -> list[str]:
    """Return the exact, ordered labels of a Postgres ENUM type.

    Introspects ``pg_type``/``pg_enum`` so callers never hardcode (and mismatch)
    enum casing. Useful to verify ``TRANSACTION_TYPE_LABELS`` still matches the
    live database, or to inject real labels into an LLM's context window.

    Returns ``[]`` when the type does not exist.
    """
    rows = await session.execute(
        text(
            """
            SELECT e.enumlabel
            FROM pg_type t
            JOIN pg_enum e ON e.enumtypid = t.oid
            WHERE t.typname = :enum_type
            ORDER BY e.enumsortorder
            """
        ),
        {"enum_type": enum_type},
    )
    return [r[0] for r in rows.fetchall()]

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
    "ledger_entries": f"""\
ledger_entries(
    id              UUID PRIMARY KEY,
    account_id      UUID,
    customer_id     UUID,
    transaction_type transactiontype,  -- ENUM, EXACT case-sensitive values: {_TX_LABELS_SQL}
    amount          NUMERIC,
    currency        TEXT,
    description     TEXT,
    category        TEXT,
    reference       TEXT,
    created_at      TIMESTAMPTZ
)""",
    "invoices": f"""\
invoices(
    id              UUID PRIMARY KEY,
    customer_id     UUID,
    invoice_number  TEXT,
    status          invoicestatus,  -- ENUM, EXACT case-sensitive values: {_INVOICE_STATUS_SQL}
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
    "products": f"""\
products(
    id                UUID PRIMARY KEY,
    sku               TEXT,
    name              TEXT,
    category          TEXT,
    unit              TEXT,          -- stored as ENUM NAME, EXACT case: {_UNIT_SQL}
    cost_price        NUMERIC,
    selling_price     NUMERIC,
    reorder_level     NUMERIC,
    reorder_quantity  NUMERIC,
    is_active         BOOLEAN,
    created_at        TIMESTAMPTZ
)""",
    "stock_levels": """\
stock_levels(
    id                UUID PRIMARY KEY,
    product_id        UUID,          -- FK products.id
    location_id       UUID,
    quantity_on_hand  NUMERIC,
    quantity_reserved NUMERIC,
    average_cost      NUMERIC,
    updated_at        TIMESTAMPTZ
)""",
    "stock_movements": f"""\
stock_movements(
    id              UUID PRIMARY KEY,
    product_id      UUID,            -- FK products.id
    sequence        INTEGER,
    movement_type   TEXT,            -- stored as ENUM NAME, EXACT case: {_MOVEMENT_TYPE_SQL}
    movement_reason TEXT,
    quantity        NUMERIC,         -- always positive
    unit_cost       NUMERIC,
    balance_after   NUMERIC,         -- on-hand snapshot after this movement
    reference_type  TEXT,
    reference_id    UUID,
    occurred_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ
)""",
}

# Agent D (d_forecaster / IntelliAgent) is the only consumer of Text-to-SQL.
# It must NEVER see users, knowledge_base, or outbox_events.
_AGENT_ALLOWED_TABLES: dict[str, frozenset[str]] = {
    "D": frozenset({"ledger_entries", "invoices", "budgets", "expenses"}),
    # Agent K (Stock Steward) does ad-hoc inventory analytics (cross-product
    # rollups, slow-movers). It must NEVER see users / finance money tables — only
    # the three inventory tables. The structural allowlist enforces this even
    # against a prompt-injected SELECT (see _assert_allowed_tables).
    "K": frozenset({"products", "stock_levels", "stock_movements"}),
    # Other agents do not use dynamic SQL; add entries here as needed.
}


# Union of every agent's allowed table set — the hard allowlist the read-only
# executor enforces structurally (not just via prompt masking).  Any SELECT that
# touches a table outside this set (users, knowledge_base, outbox_events, the
# Postgres catalog, information_schema, …) is rejected before it reaches the DB.
_READONLY_ALLOWED_TABLES: frozenset[str] = frozenset().union(
    *_AGENT_ALLOWED_TABLES.values()
)


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


def _assert_allowed_tables(tree: exp.Expression, allowed: frozenset[str]) -> None:
    """Reject a query that references any table outside ``allowed``.

    Schema masking only shapes the LLM *prompt*; it cannot stop a prompt-injected
    or hallucinated query from naming ``users`` directly.  This is the structural
    gate: every real table reference in the AST must be in the allowlist, so a
    SELECT against users / knowledge_base / pg_catalog / information_schema is
    refused even though it is a perfectly valid read-only statement.

    CTE names (``WITH foo AS (…) SELECT * FROM foo``) are derived identifiers,
    not physical tables, so they are excluded from the check.
    """
    cte_names = {
        cte.alias_or_name.lower()
        for cte in tree.find_all(exp.CTE)
        if cte.alias_or_name
    }
    for table in tree.find_all(exp.Table):
        name = table.name.lower()
        if name in cte_names:
            continue
        if name not in allowed:
            raise ValueError(
                f"Query references table '{table.name}' which is not in the "
                f"read-only allowlist — query rejected. "
                f"Allowed: {', '.join(sorted(allowed))}"
            )


def _ast_validate(query: str, allowed_tables: frozenset[str] | None = None) -> None:
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

    # Table allowlist: only enforced when a set is supplied (the read-only
    # executor passes one).  Keeps the generic make_sql_executor unrestricted.
    if allowed_tables is not None:
        _assert_allowed_tables(tree, allowed_tables)


def _validate(query: str, allowed_tables: frozenset[str] | None = None) -> None:
    """
    Two-layer read-only guard:
      1. Regex pre-filter — fast rejection of obvious forbidden keywords.
      2. sqlglot AST validation — deterministic, bypass-proof structural check.

    When ``allowed_tables`` is provided, the AST walk additionally rejects any
    query that references a table outside that set (structural schema masking).
    """
    stripped = query.strip()
    # Allow read-only CTEs (``WITH … SELECT``) as well as plain SELECTs. The
    # sqlglot AST walk below is the authoritative gate: it rejects any non-Select
    # root and any DML/DDL node nested inside a CTE body, so widening this leading
    # keyword check does not weaken the guard (verified: a CTE wrapping a
    # DELETE/INSERT still trips the forbidden-node walk in _ast_validate).
    if not stripped.upper().startswith(("SELECT", "WITH")):
        raise ValueError("Only SELECT/WITH (CTE) queries are permitted")
    if _FORBIDDEN.search(stripped):
        raise ValueError("Query contains forbidden keyword")
    # AST check is the authoritative gate — runs even when the regex passes,
    # catching obfuscation techniques that survive keyword scanning.
    _ast_validate(stripped, allowed_tables)


_MAX_ROWS = 100


def _enforce_limit(query: str) -> str:
    """
    Parse a validated SELECT and clamp its LIMIT to at most _MAX_ROWS.

    Called after _validate(), so the AST is guaranteed to be a single clean
    SELECT with no forbidden nodes.  Any existing LIMIT higher than _MAX_ROWS
    is overwritten; if no LIMIT clause exists one is injected.

    Raises ValueError if the AST cannot be parsed (should never happen after
    _validate() passes, but guards against edge-case sqlglot dialect quirks).
    """
    try:
        tree = sqlglot.parse_one(query, dialect="postgres")
    except ParseError as exc:
        raise ValueError(
            f"SQL parse error during limit enforcement: {exc}"
        ) from exc

    if tree is None or not isinstance(tree, exp.Select):
        raise ValueError("Internal: non-SELECT reached _enforce_limit")

    limit_node = tree.args.get("limit")
    if limit_node is not None:
        lit = limit_node.find(exp.Literal)
        try:
            current = int(lit.this) if lit else _MAX_ROWS + 1
        except (ValueError, TypeError):
            current = _MAX_ROWS + 1
        if current > _MAX_ROWS:
            tree = tree.limit(_MAX_ROWS)
    else:
        tree = tree.limit(_MAX_ROWS)

    return tree.sql(dialect="postgres")


def make_sql_executor(session: AsyncSession) -> Any:
    @tool
    async def execute_sql(query: str) -> list[dict[str, Any]]:
        """Run a read-only SELECT query against the Finguard PostgreSQL database.

        Args:
            query: A plain SQL SELECT statement. No parameters — embed literal
                   values directly. Maximum 100 rows returned.
        """
        _validate(query)
        safe_query = _enforce_limit(query)
        result = await session.execute(text(safe_query))
        keys = list(result.keys())
        rows = result.fetchall()
        return [dict(zip(keys, row, strict=False)) for row in rows]

    return execute_sql


@traced_tool("readonly_sql")
async def execute_readonly_sql(query: str) -> list[dict[str, Any]]:
    """
    Execute a validated SELECT query using the read-only session factory.

    Used by the Text-to-SQL CoVe workflow in Agent D and the Agent E watchdog so
    LLM-generated queries run under the finguard_readonly PostgreSQL role.  In
    addition to the read-only role boundary (defence in depth), every query is
    structurally restricted to the table allowlist so a prompt-injected or
    hallucinated SELECT cannot read users / knowledge_base / outbox_events even
    if the role grant were ever misconfigured.

    Fail-closed in production: ``ReadOnlyAsyncSessionLocal`` is bound to a
    fail-closed engine (see infrastructure/database/postgres.py) that refuses to
    fall back to the privileged engine when DATABASE_READONLY_URL is unset in
    production.
    """
    _validate(query, allowed_tables=_READONLY_ALLOWED_TABLES)
    safe_query = _enforce_limit(query)

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
        result = await session.execute(text(safe_query))
        keys = list(result.keys())
        rows = result.fetchall()
        return [dict(zip(keys, row, strict=False)) for row in rows]
