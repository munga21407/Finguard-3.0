"""
Local conftest for core unit tests.

Overrides the parent ``create_tables`` autouse fixture so these hermetic unit
tests (config validation, CSRF logic) never attempt a live database connection.
"""
from __future__ import annotations

from collections.abc import AsyncIterator

import pytest_asyncio


@pytest_asyncio.fixture(scope="session", autouse=True)
async def create_tables() -> AsyncIterator[None]:
    """No-op override — core unit tests do not touch the database."""
    yield
