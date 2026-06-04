from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from src.core.config import settings

_logger = logging.getLogger(__name__)

engine = create_async_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)

# Read-only engine for the finguard_readonly PostgreSQL role.
# Falls back to the main engine when DATABASE_READONLY_URL is not configured.
if not settings.DATABASE_READONLY_URL:
    _logger.warning(
        "DATABASE_READONLY_URL is not set — Agent D (Text-to-SQL / CoVe) will "
        "execute LLM-generated queries against the fully-privileged main database "
        "engine. Run `docker compose exec postgres psql -U finguard -d finguard "
        "-f infrastructure/db_security.sql` then set DATABASE_READONLY_URL to "
        "enforce the finguard_readonly role boundary."
    )
_readonly_url = settings.DATABASE_READONLY_URL or settings.DATABASE_URL
_readonly_engine = create_async_engine(
    _readonly_url,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
)

ReadOnlyAsyncSessionLocal = async_sessionmaker(
    bind=_readonly_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


class Base(DeclarativeBase):
    pass


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def close_db() -> None:
    await engine.dispose()
    await _readonly_engine.dispose()


async def get_db() -> AsyncIterator[AsyncSession]:
    async with AsyncSessionLocal() as session:
        yield session
