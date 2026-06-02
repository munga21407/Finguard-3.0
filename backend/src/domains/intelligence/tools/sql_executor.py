"""
Read-only SQL executor tool.

Restricted to SELECT statements; rejects any DDL or DML at the string level
before the query ever reaches the database engine.
"""
from __future__ import annotations

import re
from typing import Any

from langchain_core.tools import tool
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_FORBIDDEN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|TRUNCATE|ALTER|CREATE|REPLACE|MERGE|EXEC|EXECUTE|CALL)\b",
    re.IGNORECASE,
)


def _validate(query: str) -> None:
    stripped = query.strip()
    if not stripped.upper().startswith("SELECT"):
        raise ValueError("Only SELECT queries are permitted")
    if _FORBIDDEN.search(stripped):
        raise ValueError("Query contains forbidden keyword")


def make_sql_executor(session: AsyncSession):  # type: ignore[return]
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
