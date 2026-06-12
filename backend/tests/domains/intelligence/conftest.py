"""
Local conftest for the intelligence domain unit tests.

Overrides the parent ``create_tables`` autouse fixture so that these
hermetic unit tests never attempt a live database connection.
"""
from __future__ import annotations

from collections.abc import AsyncIterator

import pytest_asyncio


@pytest_asyncio.fixture(scope="session", autouse=True)
async def create_tables() -> AsyncIterator[None]:
    """No-op override — intelligence unit tests mock all DB access."""
    yield
