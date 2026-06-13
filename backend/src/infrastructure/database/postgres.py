from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from sqlalchemy import text
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
# In production DATABASE_READONLY_URL MUST be configured — running LLM-generated
# (Text-to-SQL) queries against the fully-privileged main engine defeats the
# defence-in-depth boundary, so we fail closed.  Outside production we fall back
# to the main engine with a loud warning to keep local dev frictionless.
def _resolve_readonly_url() -> str:
    if settings.DATABASE_READONLY_URL:
        return settings.DATABASE_READONLY_URL
    if settings.ENVIRONMENT == "production":
        raise RuntimeError(
            "DATABASE_READONLY_URL must be set in production. LLM-generated SQL "
            "(Agent D Text-to-SQL / Agent E watchdog) must run under the "
            "finguard_readonly role, never the privileged main engine. Run "
            "infrastructure/db_security.sql and set DATABASE_READONLY_URL."
        )
    _logger.warning(
        "DATABASE_READONLY_URL is not set — read-only SQL will execute against "
        "the fully-privileged main database engine. This is allowed only outside "
        "production. Run infrastructure/db_security.sql and set "
        "DATABASE_READONLY_URL to enforce the finguard_readonly role boundary."
    )
    return settings.DATABASE_URL


_readonly_url = _resolve_readonly_url()
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
    """Verify database connectivity at startup.

    Schema is owned by Alembic migrations (run as a gated deploy step), NOT by
    ``create_all`` — auto-creating tables at runtime masks migration drift and
    can leave a half-formed schema in production.
    """
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))


async def close_db() -> None:
    await engine.dispose()
    await _readonly_engine.dispose()


async def get_db() -> AsyncIterator[AsyncSession]:
    async with AsyncSessionLocal() as session:
        yield session
