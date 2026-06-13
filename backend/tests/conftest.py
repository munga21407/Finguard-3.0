import uuid
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from sqlalchemy.schema import Table

from src.core.config import settings
from src.domains.identity.dependencies import get_current_user
from src.domains.identity.models import User, UserRole
from src.infrastructure.cache.redis import close_redis, init_redis
from src.infrastructure.database.postgres import Base, get_db
from src.main import app

TEST_DATABASE_URL = settings.DATABASE_URL.replace("/finguard", "/finguard_test")

# NullPool so no asyncpg connection is reused across tests.  pytest-asyncio runs
# each test in a fresh event loop; a pooled connection created in one loop and
# reused in the next raises "another operation is in progress".  A fresh
# connection per session (disposed on close) keeps every test loop-isolated.
engine = create_async_engine(TEST_DATABASE_URL, echo=False, poolclass=NullPool)
TestingSessionLocal = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)


def _requires_pgvector(table: Table) -> bool:
    """A table needs the pgvector extension if it has a Vector column or lives
    in the dedicated ``finguard`` schema (where the vector knowledge base sits)."""
    if table.schema == "finguard":
        return True
    return any(type(col.type).__name__ == "Vector" for col in table.columns)


@pytest_asyncio.fixture(scope="session", autouse=True)
async def create_tables() -> AsyncIterator[None]:
    # knowledge_base lives in the `finguard` schema; create it unconditionally.
    async with engine.begin() as conn:
        await conn.execute(text("CREATE SCHEMA IF NOT EXISTS finguard"))

    # pgvector is absent on stock Postgres images (including CI's postgres:16).
    # Try to enable it; if unavailable, build every table EXCEPT the pgvector
    # ones so the rest of the suite still runs.  Each attempt uses its own
    # transaction since a failed CREATE EXTENSION aborts the surrounding one.
    has_vector = False
    try:
        async with engine.begin() as conn:
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        has_vector = True
    except Exception:
        has_vector = False

    tables = None if has_vector else [
        t for t in Base.metadata.sorted_tables if not _requires_pgvector(t)
    ]

    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=tables))
    yield
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.drop_all(c, tables=tables))


@pytest_asyncio.fixture(autouse=True)
async def _init_redis() -> AsyncIterator[None]:
    """Initialise the Redis connection pools for each test.

    The ASGI test transport does not run the app lifespan, so code paths that
    call ``get_auth_redis()`` / ``get_redis()`` (login lockout, token blacklist,
    conversation status) would otherwise hit an uninitialised pool.  Scoped
    per-function because redis-py async pools bind to the event loop that first
    uses them, and pytest-asyncio runs each test in its own loop.
    """
    await init_redis()
    yield
    await close_redis()


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    async with TestingSessionLocal() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    async def override_get_db() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def auth_as() -> AsyncIterator[Callable[..., User]]:
    """
    Factory that authenticates the test client as a fixed user of a given role
    by overriding ``get_current_user``.  Returns the User so the caller can
    assert on its id.  Use to exercise the RBAC matrix per role::

        viewer = auth_as(UserRole.VIEWER)
        res = await client.post("/api/v1/finance/ledger", json=...)
        assert res.status_code == 403
    """

    def _set(role: UserRole = UserRole.OWNER) -> User:
        user = User(
            id=uuid.uuid4(),
            email=f"{role.value}-{uuid.uuid4().hex[:8]}@example.com",
            hashed_password="x",
            full_name=f"{role.value} user",
            role=role,
            is_active=True,
            is_verified=True,
            created_at=datetime.now(UTC),
        )

        async def _override() -> User:
            return user

        app.dependency_overrides[get_current_user] = _override
        return user

    yield _set
    app.dependency_overrides.pop(get_current_user, None)
