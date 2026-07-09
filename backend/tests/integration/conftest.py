"""Fixtures for DB-integration tests that need Postgres.

These tests live outside ``tests/domains/intelligence`` on purpose: that package
overrides ``create_tables`` with a no-op (hermetic unit tests), whereas these
need the real session-scoped schema from the root ``tests/conftest.py``.

``finguard.agent_config`` and ``finguard.tax_rate_schedule`` live in the
``finguard`` schema, which the root ``create_tables`` skips when pgvector is
absent (CI's stock Postgres). So this fixture creates just those two
(non-pgvector) tables on the test database and clears their rows per test.
"""
from __future__ import annotations

from collections.abc import AsyncIterator

import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from src.core.config import settings
from src.domains.intelligence.models import AgentConfig, TaxRateSchedule
from src.infrastructure.database.postgres import Base

# Same test-DB derivation as the root conftest (swap only the database name).
_base_url, _, _ = settings.DATABASE_URL.rpartition("/")
_TEST_DATABASE_URL = f"{_base_url}/finguard_test"

_TABLES = [AgentConfig.__table__, TaxRateSchedule.__table__]


@pytest_asyncio.fixture
async def tuning_tables() -> AsyncIterator[None]:
    """Ensure the two tuning tables exist and start each test with empty rows."""
    engine = create_async_engine(_TEST_DATABASE_URL, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.execute(text("CREATE SCHEMA IF NOT EXISTS finguard"))
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=_TABLES))
        # Setup-time cleanup keeps tests isolated without a teardown DROP (which
        # could race a still-open test-session transaction on these tables).
        await conn.execute(text("DELETE FROM finguard.tax_rate_schedule"))
        await conn.execute(text("DELETE FROM finguard.agent_config"))
    try:
        yield
    finally:
        await engine.dispose()
