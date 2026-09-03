"""Human-in-the-loop approval for agent-proposed, value-changing actions.

An agent is always the *maker*: it lands a proposal at ``PROPOSED`` with no side
effect (:meth:`ProposalService.create_proposal`).  A human holding the action's
domain permission is the *checker*; approving replays the write through the same
guarded tool path exactly once (:meth:`ProposalService.approve`).

Two independent layers protect every release, mirroring the payable maker-checker:

* **Authority** — *who may approve* — is enforced at the endpoint by the action's
  domain permission (e.g. ``inventory:adjust`` for a stock adjustment).
* **Segregation of duties** — *not your own* — is enforced here: the reviewer must
  differ from the human who triggered the agent run (strict two-human control).  A
  permission cannot express this object-level relationship, so it lives in code.

The proposal is held ``FOR UPDATE`` across the decision so two reviewers cannot
both approve it and double-apply the write.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.core.exceptions import ForbiddenError, NotFoundError, UnprocessableError
from src.core.logging import logger
from src.domains.identity.models import User
from src.domains.identity.permissions import Permission
from src.domains.intelligence.models import AgentActionProposal, ProposalStatus
from src.domains.intelligence.security.vc_issuer import issue_vc
from src.domains.intelligence.tools.inventory_tools import propose_stock_movement
from src.domains.notifications.reviewers import notify_reviewers

# Action types whose approval replays a stock movement through the guarded tool.
ACTION_STOCK_ADJUSTMENT = "stock.adjustment"


async def _issue_decision_vc(
    proposal: AgentActionProposal, operation: str, reviewer_id: uuid.UUID
) -> None:
    """Best-effort, tamper-evident record of a proposal decision in ``trust_log``.

    Mirrors ``e_watchdog.py``'s VC-issuance pattern: never let a Mongo hiccup
    affect the outcome of an already-committed Postgres decision — the plain
    ``audit_logs`` row (written by the router via ``AuditService``) is the
    system of record regardless of whether this signed copy succeeds.
    """
    try:
        await issue_vc(
            agent_id=proposal.agent_label,
            operation=operation,
            operation_summary=(
                f"proposal {proposal.id} ({proposal.action_type}) "
                f"{operation.rsplit('.', 1)[-1]} by {reviewer_id}"
            ),
            payload={
                "proposal_id": str(proposal.id),
                "action_type": proposal.action_type,
                "payload": proposal.payload,
                "reviewer_id": str(reviewer_id),
                "applied_ref": proposal.applied_ref,
            },
        )
    except Exception as exc:
        logger.warning(
            "proposal: VC issuance failed",
            proposal_id=str(proposal.id),
            operation=operation,
            error=str(exc),
        )


class ProposalService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_proposal(
        self,
        *,
        agent_label: str,
        action_type: str,
        payload: dict[str, Any],
        triggered_by: uuid.UUID | None,
        rationale: str | None = None,
    ) -> AgentActionProposal:
        """Persist an agent proposal at PROPOSED with **no** side effect.

        Deliberately inert — the value-changing write is deferred to
        :meth:`approve`, so a proposal awaiting a second human never mutates stock
        (or burns budget, for finance action types) before sign-off.
        """
        proposal = AgentActionProposal(
            agent_label=agent_label,
            action_type=action_type,
            payload=payload,
            triggered_by=triggered_by,
            rationale=rationale,
            status=ProposalStatus.PROPOSED,
        )
        self._session.add(proposal)
        await self._session.flush()  # assign proposal.id before notifying
        # Notify reviewers who can release this action class (inventory:adjust for
        # a stock adjustment), except whoever triggered the agent. Enqueue-only.
        await notify_reviewers(
            self._session,
            permission=Permission.INVENTORY_ADJUST,
            subject="An agent action needs your review",
            template="approval_needed",
            context={
                "summary": f"{agent_label} proposed an action ({action_type}) awaiting release.",
                "detail": rationale or "",
                "review_url": f"{settings.APP_BASE_URL}/dashboard/approvals",
            },
            resource_id=proposal.id,
            key_prefix="proposal_review",
            exclude_user_id=triggered_by,
        )
        await self._session.commit()
        await self._session.refresh(proposal)
        return proposal

    async def list_pending(self, limit: int = 100) -> list[AgentActionProposal]:
        result = await self._session.execute(
            select(AgentActionProposal)
            .where(AgentActionProposal.status == ProposalStatus.PROPOSED)
            .order_by(AgentActionProposal.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def approve(
        self, proposal_id: uuid.UUID, current_user: User
    ) -> AgentActionProposal:
        """Release a pending proposal: apply its write, exactly once, mark APPLIED.

        Enforces strict segregation of duties (reviewer ≠ the human who triggered
        the agent) and, critically, applies the write **exactly once** under
        concurrency.  The guarded write path commits internally (the agent audit
        row), which would release a plain ``FOR UPDATE`` lock mid-apply, so this
        instead *claims* the proposal — flips it to APPLIED and commits — before
        touching the write.  A second reviewer blocked on the row lock unblocks,
        re-reads APPLIED, and is rejected.  If the write then fails the claim is
        rolled back to PROPOSED so it can be re-decided.
        """
        proposal = await self._get_for_update(proposal_id)
        if proposal.status is not ProposalStatus.PROPOSED:
            raise UnprocessableError(f"Proposal is already {proposal.status}")
        if (
            proposal.triggered_by is not None
            and proposal.triggered_by == current_user.id
        ):
            raise ForbiddenError(
                "The requester cannot approve their own agent action"
            )

        # Capture the write args before the claim-commit expires the ORM state
        # (async lazy-load of an expired attribute would raise).
        action_type = proposal.action_type
        payload = dict(proposal.payload)

        # ── Claim (atomic under the row lock): flip PROPOSED → APPLIED, commit ──
        proposal.status = ProposalStatus.APPLIED
        proposal.reviewed_by = current_user.id
        proposal.reviewed_at = datetime.now(UTC)
        await self._session.commit()

        # ── Apply the write; roll the claim back to PROPOSED if it refuses ──────
        try:
            applied_ref = await self._apply(
                action_type, payload, reviewer_id=current_user.id
            )
        except Exception:
            proposal.status = ProposalStatus.PROPOSED
            proposal.reviewed_by = None
            proposal.reviewed_at = None
            await self._session.commit()
            raise

        proposal.applied_ref = applied_ref
        await self._session.commit()
        await _issue_decision_vc(proposal, "proposal.approved", current_user.id)
        await self._session.refresh(proposal)
        return proposal

    async def reject(
        self, proposal_id: uuid.UUID, current_user: User
    ) -> AgentActionProposal:
        """Reject a pending proposal (no write). Reviewer must differ from requester."""
        proposal = await self._get_for_update(proposal_id)
        if proposal.status is not ProposalStatus.PROPOSED:
            raise UnprocessableError(f"Proposal is already {proposal.status}")
        if (
            proposal.triggered_by is not None
            and proposal.triggered_by == current_user.id
        ):
            raise ForbiddenError(
                "The requester cannot review their own agent action"
            )
        proposal.status = ProposalStatus.REJECTED
        proposal.reviewed_by = current_user.id
        proposal.reviewed_at = datetime.now(UTC)
        await self._session.commit()
        await _issue_decision_vc(proposal, "proposal.rejected", current_user.id)
        await self._session.refresh(proposal)
        return proposal

    # ── internals ────────────────────────────────────────────────────────────

    async def _get_for_update(self, proposal_id: uuid.UUID) -> AgentActionProposal:
        proposal = await self._session.get(
            AgentActionProposal, proposal_id, with_for_update=True
        )
        if not proposal:
            raise NotFoundError("Agent action proposal not found")
        return proposal

    async def _apply(
        self, action_type: str, payload: dict[str, Any], *, reviewer_id: uuid.UUID
    ) -> str:
        """Replay the proposal's write through its guarded tool path.

        The write inherits every ledger guard and emits an agent-attributed audit
        row (``actor_type=agent``); ``reviewer_id`` is threaded through as the
        actor so the movement is traceable to the human who released it.
        """
        if action_type == ACTION_STOCK_ADJUSTMENT:
            result = await propose_stock_movement(
                self._session,
                product_ref=str(payload["product_ref"]),
                movement_type=str(payload.get("movement_type", "adjustment")),
                quantity=float(payload.get("quantity", 0)),
                reason=payload.get("reason"),
                unit_cost=payload.get("unit_cost"),
                note=payload.get("note"),
                apply=True,
                actor_id=reviewer_id,
            )
            if result.get("status") != "applied":
                # The guarded tool refused at apply time (e.g. stock moved since the
                # proposal). Surface it; the caller rolls the claim back to PROPOSED.
                raise UnprocessableError(
                    f"Cannot apply proposal: {result.get('detail', 'rejected by service')}"
                )
            return str(result.get("detail", ""))

        raise UnprocessableError(f"Unknown action_type {action_type!r}")
