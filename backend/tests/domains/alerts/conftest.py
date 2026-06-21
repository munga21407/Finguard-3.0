"""Local conftest for hermetic alerts unit tests — no live database."""
from __future__ import annotations

from collections.abc import AsyncIterator

import pytest_asyncio


@pytest_asyncio.fixture(scope="session", autouse=True)
async def create_tables() -> AsyncIterator[None]:
    """No-op override — these unit tests exercise pure logic only."""
    yield
