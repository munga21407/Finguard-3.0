"""Human-in-the-loop approval queue for agent-proposed, value-changing actions.

Endpoints (mounted under ``/api/v1/intelligence``):
  GET  /proposals                                  — pending proposals awaiting a human sign-off
  POST /proposals/{id}/approve                     — release a stock-adjustment proposal
  POST /proposals/{id}/reject                      — decline a stock-adjustment proposal
  POST /proposals/reconciliation/{id}/approve       — release a reconciliation-match proposal
  POST /proposals/reconciliation/{id}/reject        — decline a reconciliation-match proposal

Authority is enforced per action type by the domain permission the write touches
(a stock adjustment needs ``inventory:adjust``; a reconciliation match needs
``finance:reconcile`` — both manager+). Each endpoint pins its own
``expected_action_type`` when calling the service, so a reviewer authorized for
one action class can never approve/reject a proposal of a *different* class by
guessing its id — see ``ProposalService.approve``'s docstring. Segregation of
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
    RequireFinanceReconcile,
    RequireIntelligenceRead,
    RequireInventoryAdjust,
)
from src.domains.intelligence.models import AgentActionProposal
from src.domains.intelligence.proposal_service import (
    ACTION_RECONCILIATION_MATCH,
    ACTION_STOCK_ADJUSTMENT,
    ProposalService,
)
from src.domains.intelligence.schemas import AgentActionProposalResponse
from src.infrastructure.database.postgres import get_db

router = APIRouter()

DBSession = Annotated[AsyncSession, Depends(get_db)]


def _audit_metadata(proposal: AgentActionProposal) -> dict[str, str | None]:
    return {
        "action_type": proposal.action_type,
        "agent_label": proposal.agent_label,
        "triggered_by": str(proposal.triggered_by),
        "applied_ref": proposal.applied_ref,
    }


@router.get("/proposals", response_model=list[AgentActionProposalResponse])
async def list_proposals(
    db: DBSession, _: RequireIntelligenceRead, limit: int = 100
) -> list[AgentActionProposal]:
    """The pending agent-action queue awaiting human sign-off (every action type)."""
    return await ProposalService(db).list_pending(limit=limit)


@router.post("/proposals/{proposal_id}/approve", response_model=AgentActionProposalResponse)
async def approve_proposal(
    proposal_id: uuid.UUID, db: DBSession, current_user: RequireInventoryAdjust
) -> AgentActionProposal:
    """Release a pending stock-adjustment proposal — applies its write exactly once.

    Gated by ``inventory:adjust`` (manager+); the service additionally blocks the
    human who triggered the agent from approving their own action (strict SoD).
    """
    proposal = await ProposalService(db).approve(
        proposal_id, current_user, expected_action_type=ACTION_STOCK_ADJUSTMENT
    )
    await AuditService(db).record_user_action_safe(
        current_user,
        AuditAction.AGENT_PROPOSAL_APPROVED,
        "agent_action_proposal",
        resource_id=proposal.id,
        metadata=_audit_metadata(proposal),
    )
    return proposal


@router.post("/proposals/{proposal_id}/reject", response_model=AgentActionProposalResponse)
async def reject_proposal(
    proposal_id: uuid.UUID, db: DBSession, current_user: RequireInventoryAdjust
) -> AgentActionProposal:
    """Decline a pending stock-adjustment proposal (no write)."""
    proposal = await ProposalService(db).reject(
        proposal_id, current_user, expected_action_type=ACTION_STOCK_ADJUSTMENT
    )
    await AuditService(db).record_user_action_safe(
        current_user,
        AuditAction.AGENT_PROPOSAL_REJECTED,
        "agent_action_proposal",
        resource_id=proposal.id,
        metadata=_audit_metadata(proposal),
    )
    return proposal


@router.post(
    "/proposals/reconciliation/{proposal_id}/approve",
    response_model=AgentActionProposalResponse,
)
async def approve_reconciliation_proposal(
    proposal_id: uuid.UUID, db: DBSession, current_user: RequireFinanceReconcile
) -> AgentActionProposal:
    """Release a pending reconciliation-match proposal (Agent C's Pass 2 output).

    Gated by ``finance:reconcile`` (manager+) — the same permission that gates
    importing bank statements, since both settle real ledger state. The service
    additionally blocks the human who triggered the agent from approving their
    own action (strict SoD).
    """
    proposal = await ProposalService(db).approve(
        proposal_id, current_user, expected_action_type=ACTION_RECONCILIATION_MATCH
    )
    await AuditService(db).record_user_action_safe(
        current_user,
        AuditAction.AGENT_PROPOSAL_APPROVED,
        "agent_action_proposal",
        resource_id=proposal.id,
        metadata=_audit_metadata(proposal),
    )
    return proposal


@router.post(
    "/proposals/reconciliation/{proposal_id}/reject",
    response_model=AgentActionProposalResponse,
)
async def reject_reconciliation_proposal(
    proposal_id: uuid.UUID, db: DBSession, current_user: RequireFinanceReconcile
) -> AgentActionProposal:
    """Decline a pending reconciliation-match proposal (no write)."""
    proposal = await ProposalService(db).reject(
        proposal_id, current_user, expected_action_type=ACTION_RECONCILIATION_MATCH
    )
    await AuditService(db).record_user_action_safe(
        current_user,
        AuditAction.AGENT_PROPOSAL_REJECTED,
        "agent_action_proposal",
        resource_id=proposal.id,
        metadata=_audit_metadata(proposal),
    )
    return proposal
