"""DB-integration tests for the Sprint-1 runtime tuning layer (needs Postgres).

Covers the parts the hermetic unit tests can't: the real ``effective_from <= as_of``
SQL selection and the ``agent_config`` write path.
"""
from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domains.intelligence.db_tuning import (
    get_effective_auditor_tuning,
    set_tax_rate,
    upsert_agent_config,
)
from src.domains.intelligence.models import AgentConfig
from src.domains.intelligence.tuning import AuditorTuning, clear_db_overlay


@pytest.fixture(autouse=True)
def _reset_overlay() -> None:
    clear_db_overlay()
    yield
    clear_db_overlay()


@pytest.mark.asyncio
async def test_effective_tax_uses_period_correct_rate(
    db_session: AsyncSession, tuning_tables: None
) -> None:
    await set_tax_rate(db_session, "vat_rate", 0.14, dt.date(2023, 1, 1))
    await set_tax_rate(db_session, "vat_rate", 0.16, dt.date(2024, 1, 1))

    eff_2023 = await get_effective_auditor_tuning(db_session, dt.date(2023, 6, 1))
    assert eff_2023.vat_rate == 0.14   # SQL WHERE effective_from <= as_of picks the 2023 row

    eff_2024 = await get_effective_auditor_tuning(db_session, dt.date(2024, 6, 1))
    assert eff_2024.vat_rate == 0.16   # latest row on/after 2024-01-01


@pytest.mark.asyncio
async def test_effective_tax_defaults_when_no_row(
    db_session: AsyncSession, tuning_tables: None
) -> None:
    eff = await get_effective_auditor_tuning(db_session, dt.date(2024, 1, 1))
    assert eff.vat_rate == AuditorTuning().vat_rate
    assert eff.cit_rate == AuditorTuning().cit_rate


@pytest.mark.asyncio
async def test_upsert_agent_config_writes_row(
    db_session: AsyncSession, tuning_tables: None
) -> None:
    await upsert_agent_config(db_session, "reconciler", {"txn_batch": 7})
    row = await db_session.scalar(
        select(AgentConfig).where(AgentConfig.section == "reconciler")
    )
    assert row is not None
    assert row.payload["txn_batch"] == 7


@pytest.mark.asyncio
async def test_upsert_agent_config_rejects_invalid(
    db_session: AsyncSession, tuning_tables: None
) -> None:
    with pytest.raises(ValueError):
        await upsert_agent_config(db_session, "auditor", {"vat_rate": 1.6})   # out of range
    with pytest.raises(ValueError):
        await upsert_agent_config(db_session, "bogus_section", {})            # unknown section
    # Nothing was written.
    rows = (await db_session.execute(select(AgentConfig))).scalars().all()
    assert rows == []
