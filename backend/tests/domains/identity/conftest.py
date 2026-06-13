"""
Identity-domain test fixtures.

Identity tests exercise the REAL authentication flow (register / login /
verification), so ``get_current_user`` is deliberately NOT overridden here.

Because registration bootstraps the first account as a verified OWNER, the
``users`` table is truncated before each test so "first user" is deterministic
regardless of execution order or leftover rows from an interrupted run.
"""
from __future__ import annotations

from collections.abc import AsyncIterator, Iterator

import pytest
import pytest_asyncio
from sqlalchemy import text

from src.domains.identity.router import limiter
from src.infrastructure.cache.redis import get_auth_redis
from tests.conftest import TestingSessionLocal


@pytest_asyncio.fixture(autouse=True)
async def _clean_users() -> AsyncIterator[None]:
    async with TestingSessionLocal() as session:
        await session.execute(text("TRUNCATE TABLE users CASCADE"))
        await session.commit()
    # Clear lockout counters and the token blacklist (auth Redis, DB 1) so
    # lockout / revocation state does not leak between tests.
    await get_auth_redis().flushdb()
    yield


@pytest.fixture(autouse=True)
def _disable_rate_limit() -> Iterator[None]:
    """The login route is rate-limited 5/min per IP; all tests share 127.0.0.1,
    so disable the limiter to keep the suite from tripping 429s."""
    previously = limiter.enabled
    limiter.enabled = False
    yield
    limiter.enabled = previously
