from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from pathlib import Path

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


def _expected_head_revision() -> str | None:
    """Best-effort: the latest Alembic head revision from the versions/ tree.

    Returns None if alembic or the script directory can't be located — the
    caller degrades to the weaker "is there *any* version" check rather than
    failing on an environment quirk.
    """
    try:
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        # postgres.py → database → infrastructure → src → <app root>
        app_root = Path(__file__).resolve().parents[3]
        script_location = app_root / "alembic"
        if not (script_location / "versions").is_dir():
            return None
        cfg = Config()
        cfg.set_main_option("script_location", str(script_location))
        return ScriptDirectory.from_config(cfg).get_current_head()
    except Exception:  # noqa: BLE001 — head detection is advisory, never fatal
        return None


async def verify_schema_migrated() -> None:
    """Refuse to serve traffic against an unmigrated / drifted schema.

    Enforces the migrations-on-deploy contract: the app must run *after*
    ``alembic upgrade head`` (the compose ``migrate`` service or the deploy
    pipeline). In production a missing/behind ``alembic_version`` is fatal; in
    dev it's a loud warning so local non-compose workflows stay frictionless —
    the same fail-in-prod / warn-in-dev pattern as the read-only engine guard.
    """
    async with engine.connect() as conn:
        try:
            result = await conn.execute(text("SELECT version_num FROM alembic_version"))
            current = result.scalar_one_or_none()
        except Exception:  # noqa: BLE001 — table absent ⇒ never migrated
            current = None

    is_prod = settings.ENVIRONMENT == "production"

    if current is None:
        msg = (
            "Database has not been migrated (no alembic_version row). Run "
            "`alembic -c alembic/alembic.ini upgrade head` before starting the app."
        )
        if is_prod:
            raise RuntimeError(msg)
        _logger.warning("%s — allowed outside production.", msg)
        return

    head = _expected_head_revision()
    if head is not None and current != head:
        msg = (
            f"Database schema is at revision {current!r} but the code expects "
            f"{head!r}. Run `alembic upgrade head` to apply pending migrations."
        )
        if is_prod:
            raise RuntimeError(msg)
        _logger.warning("%s — allowed outside production.", msg)
        return

    _logger.info("Schema migration check passed (alembic head=%s).", current)


async def close_db() -> None:
    await engine.dispose()
    await _readonly_engine.dispose()


async def get_db() -> AsyncIterator[AsyncSession]:
    async with AsyncSessionLocal() as session:
        yield session
