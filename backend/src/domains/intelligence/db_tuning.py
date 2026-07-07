"""Runtime (DB-backed) layer over the static agent tuning in ``tuning.py``.

``tuning.py`` provides env + code-default tuning read synchronously.  This module
adds the two deferred Sprint-1 pieces:

1. **Runtime overlay** — ``refresh_agent_tuning_from_db`` reads the
   ``finguard.agent_config`` table and installs its sections as the process
   overlay (``tuning.set_db_overlay``), so an operator retunes an agent by
   writing a row — no restart.  Section-level precedence stays env > DB > default.
   Refreshes are TTL-gated so calling it at every agent invocation is cheap.

2. **Effective-dated tax** — ``get_effective_auditor_tuning`` overlays the
   ``finguard.tax_rate_schedule`` rows effective at a given date onto the
   ``AuditorTuning``, so a historical audit uses period-correct rates.

Invalid overlay sections are validated and dropped (a bad runtime row must never
crash an agent), unlike the import-time env validator which can hard-fail in prod.
"""
from __future__ import annotations

import time
from dataclasses import replace
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.logging import logger
from src.domains.intelligence.models import AgentConfig, TaxRateSchedule
from src.domains.intelligence.tuning import (
    _SECTIONS,
    AuditorTuning,
    coerce_section,
    get_auditor_tuning,
    set_db_overlay,
    validate_agent_tuning,
)
from src.domains.intelligence.tuning import AgentTuning as _AgentTuning
from src.infrastructure.database.postgres import AsyncSessionLocal

# Maps a tax_rate_schedule.rate_key to the AuditorTuning field it overrides.
_TAX_RATE_KEYS: frozenset[str] = frozenset({
    "vat_rate",
    "vat_threshold_annual_kes",
    "cit_rate",
    "tot_rate",
    "aml_reporting_threshold_kes",
})

_REFRESH_TTL_SECONDS = 60.0
_last_refresh: float = 0.0


def _validate_section(section: str, instance: Any) -> list[str]:
    """Return validation problems for a single tuning section instance."""
    candidate = _AgentTuning(**{section: instance})
    prefix = f"{section}."
    return [p for p in validate_agent_tuning(candidate) if p.startswith(prefix)]


async def refresh_agent_tuning_from_db(*, force: bool = False) -> None:
    """Load ``agent_config`` rows into the tuning overlay (TTL-gated).

    Cheap to call on every agent invocation: it no-ops unless the TTL has
    elapsed (or ``force=True``).  Opens its own short-lived session so it never
    interferes with a caller's open transaction (e.g. the reconciler's
    ``session.begin()`` batch).  Each row is coerced + validated; invalid
    sections are logged and skipped so a bad runtime override never breaks an
    agent run.
    """
    global _last_refresh
    now = time.monotonic()
    if not force and (now - _last_refresh) < _REFRESH_TTL_SECONDS:
        return

    try:
        async with AsyncSessionLocal() as session:
            rows = (await session.execute(select(AgentConfig))).scalars().all()
    except Exception as exc:  # noqa: BLE001 — DB hiccup must not break the agent
        logger.warning("db_tuning: agent_config read failed; keeping current overlay",
                       error=str(exc))
        return

    overlay: dict[str, Any] = {}
    for row in rows:
        if row.section not in _SECTIONS:
            logger.warning("db_tuning: ignoring unknown agent_config section",
                           section=row.section)
            continue
        try:
            instance = coerce_section(row.section, dict(row.payload or {}))
        except (ValueError, TypeError) as exc:
            logger.warning("db_tuning: invalid agent_config payload; skipping section",
                           section=row.section, error=str(exc))
            continue
        problems = _validate_section(row.section, instance)
        if problems:
            logger.warning("db_tuning: agent_config section failed validation; skipping",
                           section=row.section, problems=problems)
            continue
        overlay[row.section] = instance

    set_db_overlay(overlay)
    _last_refresh = now
    logger.info("db_tuning: tuning overlay refreshed", sections=sorted(overlay))


async def get_effective_auditor_tuning(
    session: AsyncSession, as_of: date | None = None
) -> AuditorTuning:
    """Return AuditorTuning with tax rates effective at ``as_of`` (default today).

    For each tax rate key, the row with the greatest ``effective_from <= as_of``
    wins; keys with no schedule row keep their env/overlay/default value.
    """
    base = get_auditor_tuning()
    when = as_of or date.today()

    try:
        rows = (
            await session.execute(
                select(TaxRateSchedule).where(TaxRateSchedule.effective_from <= when)
            )
        ).scalars().all()
    except Exception as exc:  # noqa: BLE001 — degrade to base rates on DB error
        logger.warning("db_tuning: tax_rate_schedule read failed; using base rates",
                       error=str(exc))
        return base

    # Keep the latest effective_from per rate_key.
    latest: dict[str, tuple[date, float]] = {}
    for row in rows:
        if row.rate_key not in _TAX_RATE_KEYS:
            continue
        eff = row.effective_from
        if row.rate_key not in latest or eff > latest[row.rate_key][0]:
            latest[row.rate_key] = (eff, float(row.rate))

    if not latest:
        return base

    overrides = {key: val for key, (_, val) in latest.items()}
    return replace(base, **overrides)


# ---------------------------------------------------------------------------
# Admin writes (used by an operator-facing service/endpoint)
# ---------------------------------------------------------------------------

async def upsert_agent_config(
    session: AsyncSession,
    section: str,
    payload: dict[str, Any],
    *,
    updated_by: Any | None = None,
) -> None:
    """Validate and upsert an ``agent_config`` override, then refresh the overlay.

    Raises ValueError if the section is unknown or the payload is invalid, so a
    bad admin write is rejected at the source rather than silently dropped later.
    """
    instance = coerce_section(section, payload)  # raises on unknown section / keys
    problems = _validate_section(section, instance)
    if problems:
        raise ValueError(f"invalid tuning for {section}: {'; '.join(problems)}")

    stmt = (
        pg_insert(AgentConfig)
        .values(section=section, payload=payload, updated_by=updated_by)
        .on_conflict_do_update(
            index_elements=[AgentConfig.section],
            set_={"payload": payload, "updated_by": updated_by},
        )
    )
    await session.execute(stmt)
    await session.commit()
    await refresh_agent_tuning_from_db(force=True)


async def list_tax_rates(session: AsyncSession) -> list[TaxRateSchedule]:
    """Return all tax-rate schedule rows ordered by key then effective date."""
    result = await session.execute(
        select(TaxRateSchedule).order_by(
            TaxRateSchedule.rate_key, TaxRateSchedule.effective_from
        )
    )
    return list(result.scalars().all())


async def set_tax_rate(
    session: AsyncSession,
    rate_key: str,
    rate: float,
    effective_from: date,
    *,
    note: str | None = None,
) -> None:
    """Insert/replace a tax-rate schedule row for (rate_key, effective_from)."""
    if rate_key not in _TAX_RATE_KEYS:
        raise ValueError(f"unknown tax rate_key {rate_key!r}")
    stmt = (
        pg_insert(TaxRateSchedule)
        .values(rate_key=rate_key, effective_from=effective_from, rate=rate, note=note)
        .on_conflict_do_update(
            index_elements=[TaxRateSchedule.rate_key, TaxRateSchedule.effective_from],
            set_={"rate": rate, "note": note},
        )
    )
    await session.execute(stmt)
    await session.commit()
