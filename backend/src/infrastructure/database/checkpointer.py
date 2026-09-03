"""LangGraph Postgres checkpointer lifecycle — supervisor-graph replayability.

Persists ``OrchestratorState`` after every graph node (see
``orchestrator.py::build_graph``) so a killed/failed run can resume from its
last completed node instead of re-executing from ``START`` — see
``routers/conversations.py``'s ``/conversation/{session_id}/resume``.

Owns its own connection pool: ``AsyncPostgresSaver`` speaks psycopg (v3), not
SQLAlchemy/asyncpg, so it can't reuse ``postgres.py``'s engine — same DSN
(``settings.DATABASE_URL``), reformatted for psycopg's plain ``postgresql://``
scheme (SQLAlchemy's ``postgresql+asyncpg://`` driver suffix isn't a psycopg
DSN component).

Table schema is owned by the Alembic migration
``0025_langgraph_checkpoint_tables`` (this project's migrations-on-deploy
contract — see ``postgres.py::verify_schema_migrated()``), NOT by calling
``.setup()`` here — ``.setup()`` is only for local/first-run convenience and
is deliberately not invoked in this module.
"""
from __future__ import annotations

import logging
import os

# Restrict checkpoint deserialization to a built-in allowlist of safe types
# (datetime/uuid/decimal/collections/...) rather than the permissive default,
# which would import-and-execute any Python callable embedded in checkpoint
# data — relevant if the DB is ever compromised. Must be set before
# AsyncPostgresSaver/JsonPlusSerializer is constructed. `setdefault` so an
# explicit operator override still wins. Safe here: OrchestratorState's
# `context` is plain dict/list/str (verified — every agent writes via
# `.model_dump()`), and LangChain `BaseMessage`s use their own `Reviver`-based
# JSON scheme, not this msgpack ext-type fallback — so strict mode doesn't
# affect what this app actually stores in checkpoints.
os.environ.setdefault("LANGGRAPH_STRICT_MSGPACK", "true")

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver  # noqa: E402
from psycopg.rows import dict_row  # noqa: E402
from psycopg_pool import AsyncConnectionPool  # noqa: E402

from src.core.config import settings  # noqa: E402

_logger = logging.getLogger(__name__)

_pool: AsyncConnectionPool | None = None
_checkpointer: AsyncPostgresSaver | None = None


def _psycopg_dsn() -> str:
    """SQLAlchemy's asyncpg DSN, reformatted for psycopg's plain scheme."""
    return settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://", 1)


async def init_checkpointer() -> None:
    """No-op unless ``LANGGRAPH_CHECKPOINTING_ENABLED`` — see config.py."""
    global _pool, _checkpointer

    if not settings.LANGGRAPH_CHECKPOINTING_ENABLED:
        return

    _pool = AsyncConnectionPool(
        conninfo=_psycopg_dsn(),
        max_size=10,
        open=False,
        # autocommit + dict_row are both required by AsyncPostgresSaver — see
        # langgraph-checkpoint-postgres's README "Usage" note (without
        # dict_row, column-by-name access inside the saver raises TypeError).
        kwargs={"autocommit": True, "row_factory": dict_row, "prepare_threshold": 0},
    )
    await _pool.open()

    _checkpointer = AsyncPostgresSaver(_pool)  # type: ignore[arg-type]
    _logger.info("LangGraph Postgres checkpointer initialised")


async def close_checkpointer() -> None:
    global _pool, _checkpointer
    if _pool is not None:
        await _pool.close()
    _pool = None
    _checkpointer = None


def get_checkpointer() -> AsyncPostgresSaver | None:
    """Returns None when checkpointing is disabled — callers compile the graph
    without a checkpointer in that case, identical to pre-replayability
    behavior."""
    return _checkpointer
