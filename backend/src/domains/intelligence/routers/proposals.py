"""Human-in-the-loop approval queue for agent-proposed, value-changing actions.

Endpoints (mounted under ``/api/v1/intelligence``):
  GET  /proposals                     — pending proposals awaiting a human sign-off
  POST /proposals/{id}/approve        — release a proposal (applies the write, once)
  POST /proposals/{id}/reject         — decline a proposal (no write)

Authority is enforced per action type by the domain permission the write touches
(a stock adjustment needs ``inventory:adjust``, i.e. manager+).  Segregation of
duties — the reviewer must differ from the human who triggered the agent — lives
in :class:`ProposalService`, because a permission cannot express that object-level
relationship.
"""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.domains.audit.models import AuditAction
from src.domains.audit.service import AuditService
from src.domains.identity.dependencies import (
    RequireIntelligenceRead,
    RequireInventoryAdjust,
)
from src.domains.intelligence.models import AgentActionProposal
from src.domains.intelligence.proposal_service import ProposalService
from src.domains.intelligence.schemas import AgentActionProposalResponse
from src.infrastructure.database.postgres import get_db

router = APIRouter()

DBSession = Annotated[AsyncSession, Depends(get_db)]

# NOTE: the current sole action type ("stock.adjustment") is gated by
# ``inventory:adjust`` directly on the endpoints below. When a second action type
# is added whose approval needs a *different* permission (e.g. a finance proposal
# needing ``finance:approve``), split the approve/reject endpoints per action type
# rather than widening this one — keep authority explicit per route.


@router.get("/proposals", response_model=list[AgentActionProposalResponse])
async def list_proposals(
    db: DBSession, _: RequireIntelligenceRead, limit: int = 100
) -> list[AgentActionProposal]:
    """The pending agent-action queue awaiting human sign-off."""
    return await ProposalService(db).list_pending(limit=limit)


@router.post("/proposals/{proposal_id}/approve", response_model=AgentActionProposalResponse)
async def approve_proposal(
    proposal_id: uuid.UUID, db: DBSession, current_user: RequireInventoryAdjust
) -> AgentActionProposal:
    """Release a pending agent proposal — applies its write exactly once.

    Gated by ``inventory:adjust`` (manager+); the service additionally blocks the
    human who triggered the agent from approving their own action (strict SoD).
    """
    proposal = await ProposalService(db).approve(proposal_id, current_user)
    await AuditService(db).record_user_action_safe(
        current_user,
        AuditAction.AGENT_PROPOSAL_APPROVED,
        "agent_action_proposal",
        resource_id=proposal.id,
        metadata={
            "action_type": proposal.action_type,
            "agent_label": proposal.agent_label,
            "triggered_by": str(proposal.triggered_by),
            "applied_ref": proposal.applied_ref,
        },
    )
    return proposal


@router.post("/proposals/{proposal_id}/reject", response_model=AgentActionProposalResponse)
async def reject_proposal(
    proposal_id: uuid.UUID, db: DBSession, current_user: RequireInventoryAdjust
) -> AgentActionProposal:
    """Decline a pending agent proposal (no write)."""
    proposal = await ProposalService(db).reject(proposal_id, current_user)
    await AuditService(db).record_user_action_safe(
        current_user,
        AuditAction.AGENT_PROPOSAL_REJECTED,
        "agent_action_proposal",
        resource_id=proposal.id,
        metadata={
            "action_type": proposal.action_type,
            "agent_label": proposal.agent_label,
            "triggered_by": str(proposal.triggered_by),
        },
    )
    return proposal
