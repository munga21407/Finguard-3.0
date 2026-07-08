"""Local conftest for the agent eval harness.

The deterministic evals (tax math, HMM/anomaly, bankability, supervisor routing
contract) are pure functions / fully mocked — they need no database. Override the
root ``create_tables`` autouse fixture with a no-op so they run without Postgres
(the LLM-judge evals are gated separately by ``RUN_LLM_EVALS`` + a marker).
"""
from __future__ import annotations

from collections.abc import AsyncIterator

import pytest_asyncio


@pytest_asyncio.fixture(scope="session", autouse=True)
async def create_tables() -> AsyncIterator[None]:
    """No-op override — eval tests do not touch the database."""
    yield
