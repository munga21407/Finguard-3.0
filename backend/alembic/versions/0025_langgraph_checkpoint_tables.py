"""LangGraph Postgres checkpointer tables (supervisor graph replayability)

Creates the exact schema ``AsyncPostgresSaver.setup()`` (langgraph-checkpoint-postgres
3.1.2) would create, run through Alembic instead of at app startup so it stays inside
the normal migrations-on-deploy contract (``postgres.py::verify_schema_migrated()``).
The ``checkpoint_migrations`` bookkeeping row is backfilled to the same effect, so a
stray call to ``.setup()`` later (e.g. in a test fixture) is a correct no-op rather than
a duplicate-table error.

Index creation uses plain ``CREATE INDEX`` (not the library's ``CONCURRENTLY`` variant):
these tables are empty at migration time, so there's no long-lived lock to avoid, and
``CONCURRENTLY`` cannot run inside Alembic's transactional DDL without an
autocommit-block escape hatch this project doesn't otherwise use.

These tables hold full serialized graph state (LLM messages, tool outputs) — not
app data the Text-to-SQL agent (Agent D) is meant to introspect — so explicitly
carve them out of ``finguard_readonly``'s blanket ``ALTER DEFAULT PRIVILEGES`` SELECT
grant (see infrastructure/db_security.sql), same defense-in-depth posture as that
file's explicit write/sequence/function revokes.

Revision ID: 0025_langgraph_checkpoint_tables
Revises: 0024_user_email_verified
Create Date: 2026-09-03 00:00:00.000000
"""
from __future__ import annotations

from alembic import op

revision = "0025_langgraph_checkpoint_tables"
down_revision = "0024_user_email_verified"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS checkpoint_migrations (
            v INTEGER PRIMARY KEY
        )
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS checkpoints (
            thread_id TEXT NOT NULL,
            checkpoint_ns TEXT NOT NULL DEFAULT '',
            checkpoint_id TEXT NOT NULL,
            parent_checkpoint_id TEXT,
            type TEXT,
            checkpoint JSONB NOT NULL,
            metadata JSONB NOT NULL DEFAULT '{}',
            PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id)
        )
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS checkpoint_blobs (
            thread_id TEXT NOT NULL,
            checkpoint_ns TEXT NOT NULL DEFAULT '',
            channel TEXT NOT NULL,
            version TEXT NOT NULL,
            type TEXT NOT NULL,
            blob BYTEA,
            PRIMARY KEY (thread_id, checkpoint_ns, channel, version)
        )
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS checkpoint_writes (
            thread_id TEXT NOT NULL,
            checkpoint_ns TEXT NOT NULL DEFAULT '',
            checkpoint_id TEXT NOT NULL,
            task_id TEXT NOT NULL,
            idx INTEGER NOT NULL,
            channel TEXT NOT NULL,
            type TEXT,
            blob BYTEA NOT NULL,
            task_path TEXT NOT NULL DEFAULT '',
            PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id, task_id, idx)
        )
    """)

    op.execute(
        "CREATE INDEX IF NOT EXISTS checkpoints_thread_id_idx ON checkpoints(thread_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS checkpoint_blobs_thread_id_idx "
        "ON checkpoint_blobs(thread_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS checkpoint_writes_thread_id_idx "
        "ON checkpoint_writes(thread_id)"
    )

    # Mirror what AsyncPostgresSaver.setup() would record (10 migrations, v0..v9
    # in the 3.1.2 MIGRATIONS list) so a later .setup() call sees "already current"
    # instead of re-running DDL this migration already applied.
    op.execute("""
        INSERT INTO checkpoint_migrations (v)
        SELECT v FROM generate_series(0, 9) AS v
        ON CONFLICT (v) DO NOTHING
    """)

    # Defense in depth: these tables aren't app data — keep them out of the
    # Text-to-SQL read-only boundary's default SELECT grant.
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'finguard_readonly') THEN
                REVOKE SELECT ON checkpoints, checkpoint_blobs, checkpoint_writes,
                    checkpoint_migrations FROM finguard_readonly;
            END IF;
        END
        $$;
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS checkpoint_writes")
    op.execute("DROP TABLE IF EXISTS checkpoint_blobs")
    op.execute("DROP TABLE IF EXISTS checkpoints")
    op.execute("DROP TABLE IF EXISTS checkpoint_migrations")
