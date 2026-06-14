"""
The app must refuse to serve traffic against an un-migrated schema in
production (fail closed), while local dev only warns. Mirrors the read-only
engine guard's fail-in-prod / warn-in-dev contract.
"""
from __future__ import annotations

import pytest
from sqlalchemy import text

from src.infrastructure.database import postgres
from tests.conftest import engine as test_engine


def test_expected_head_revision_resolves() -> None:
    """Head detection works against the repo's alembic/versions tree."""
    head = postgres._expected_head_revision()
    assert isinstance(head, str) and head, "should resolve a concrete head revision"


@pytest.mark.asyncio
async def test_verify_raises_in_production_when_unmigrated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(postgres, "engine", test_engine)
    monkeypatch.setattr(postgres.settings, "ENVIRONMENT", "production")
    # The test DB is built via create_all and has no alembic_version row.
    async with test_engine.begin() as conn:
        await conn.execute(text("DROP TABLE IF EXISTS alembic_version"))

    with pytest.raises(RuntimeError, match="has not been migrated"):
        await postgres.verify_schema_migrated()


@pytest.mark.asyncio
async def test_verify_warns_outside_production_when_unmigrated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(postgres, "engine", test_engine)
    monkeypatch.setattr(postgres.settings, "ENVIRONMENT", "development")
    async with test_engine.begin() as conn:
        await conn.execute(text("DROP TABLE IF EXISTS alembic_version"))

    # Must NOT raise outside production — keeps local non-compose dev frictionless.
    await postgres.verify_schema_migrated()
