"""Intelligence admin — runtime agent tuning + effective-dated tax rates.

  GET  /admin/agent-tuning              — view the effective (env > DB > default) tuning
  PUT  /admin/agent-tuning/{section}    — upsert a runtime override for one section
  GET  /admin/tax-rates                 — list the effective-dated tax-rate schedule
  PUT  /admin/tax-rates/{rate_key}      — set/replace a tax rate effective from a date

Restricted to ``USER_MANAGE`` (ADMIN / OWNER) — the same guard as the KRA
knowledge-base ingest — so only operators can retune agents or change tax rates
without terminal access. The write endpoints delegate to the validated
``db_tuning`` service functions; a bad override is rejected as ``422`` rather than
silently dropped. See ``intelligence/tuning.py`` + ``intelligence/db_tuning.py``.
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.logging import logger
from src.domains.identity.dependencies import RequireUserManage
from src.domains.intelligence.db_tuning import (
    list_tax_rates,
    refresh_agent_tuning_from_db,
    set_tax_rate,
    upsert_agent_config,
)
from src.domains.intelligence.schemas import (
    AdminTuningActionResponse,
    AgentTuningSectionUpdate,
    AgentTuningView,
    TaxRateUpsert,
    TaxRateView,
)
from src.domains.intelligence.tuning import get_agent_tuning, valid_sections
from src.infrastructure.database.postgres import get_db

router = APIRouter()

DBSession = Annotated[AsyncSession, Depends(get_db)]


@router.get("/admin/agent-tuning", response_model=AgentTuningView)
async def get_agent_tuning_view(current_user: RequireUserManage) -> AgentTuningView:
    """Return the currently effective tuning (env > DB overlay > code default)."""
    await refresh_agent_tuning_from_db(force=True)
    tuning = get_agent_tuning()
    return AgentTuningView(
        reconciler=asdict(tuning.reconciler),
        watchdog=asdict(tuning.watchdog),
        auditor=asdict(tuning.auditor),
        bankability=asdict(tuning.bankability),
        classifier=asdict(tuning.classifier),
        receipt=asdict(tuning.receipt),
    )


@router.put("/admin/agent-tuning/{section}", response_model=AdminTuningActionResponse)
async def update_agent_tuning(
    section: str,
    body: AgentTuningSectionUpdate,
    current_user: RequireUserManage,
    db: DBSession,
) -> AdminTuningActionResponse:
    """Upsert a runtime override for one tuning section (applies without restart)."""
    if section not in valid_sections():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown tuning section '{section}'. Valid: {list(valid_sections())}",
        )
    try:
        await upsert_agent_config(db, section, body.payload, updated_by=current_user.id)
    except (ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    logger.info(
        "agent tuning override applied",
        actor_id=str(current_user.id),
        section=section,
        keys=sorted(body.payload),
    )
    return AdminTuningActionResponse(target=section, status="applied")


@router.get("/admin/tax-rates", response_model=list[TaxRateView])
async def list_tax_rate_schedule(
    current_user: RequireUserManage, db: DBSession
) -> list[TaxRateView]:
    """List the effective-dated tax-rate schedule Agent F resolves against."""
    rows = await list_tax_rates(db)
    return [
        TaxRateView(
            rate_key=r.rate_key,
            rate=float(r.rate),
            effective_from=r.effective_from,
            note=r.note,
        )
        for r in rows
    ]


@router.put("/admin/tax-rates/{rate_key}", response_model=AdminTuningActionResponse)
async def upsert_tax_rate(
    rate_key: str,
    body: TaxRateUpsert,
    current_user: RequireUserManage,
    db: DBSession,
) -> AdminTuningActionResponse:
    """Set/replace the tax rate for ``rate_key`` effective from ``effective_from``."""
    try:
        await set_tax_rate(db, rate_key, body.rate, body.effective_from, note=body.note)
    except (ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    logger.info(
        "tax rate upserted",
        actor_id=str(current_user.id),
        rate_key=rate_key,
        rate=body.rate,
        effective_from=str(body.effective_from),
    )
    return AdminTuningActionResponse(target=rate_key, status="applied")
