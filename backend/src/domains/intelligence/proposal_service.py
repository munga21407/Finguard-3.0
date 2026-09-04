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
from src.domains.intelligence.agent_registry import mutation_kinds
from src.domains.intelligence.models import AgentActionProposal, ProposalStatus
from src.domains.intelligence.security.vc_issuer import issue_vc, payload_hash, require_task_vc
from src.domains.intelligence.tools.inventory_tools import propose_stock_movement
from src.domains.notifications.reviewers import notify_reviewers

# Action types whose approval replays a write through a guarded tool path.
ACTION_STOCK_ADJUSTMENT = "stock.adjustment"
ACTION_RECONCILIATION_MATCH = "reconciliation.match"

# `agent_label` on the proposal is a human-readable node name for the
# notification/UI copy (e.g. "k_stockkeeper"), NOT the registry `agent_id`
# ("K") that `agent_cards`/`vc_issuer` key off of — those two must not be
# conflated, or `get_card()` raises KeyError (silently swallowed below) and
# the decision never gets a signed VC. Map action_type -> the canonical
# registry id here instead of reusing the display label.
_ACTION_AGENT_ID: dict[str, str] = {
    ACTION_STOCK_ADJUSTMENT: "K",
    ACTION_RECONCILIATION_MATCH: "C",
}

# Authority to *release* a proposal is per-action-type (see routers/proposals.py's
# split-endpoint rationale) — this dict only drives who gets the "needs your
# review" notification at creation; it never gates the approve/reject call
# itself (that's the router's job, via a Require* dependency per action type).
_ACTION_NOTIFY_PERMISSION: dict[str, Permission] = {
    ACTION_STOCK_ADJUSTMENT: Permission.INVENTORY_ADJUST,
    ACTION_RECONCILIATION_MATCH: Permission.FINANCE_RECONCILE,
}


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
            agent_id=_ACTION_AGENT_ID.get(proposal.action_type, proposal.agent_label),
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
        (or burns budget, for finance action types) before sign-off. A task-scoped
        VC (audit/defense-in-depth, shadow mode by default — see
        ``vc_issuer.require_task_vc``) attests that *this creation call* was
        authorized — a different claim from ``payload_hash`` below, which attests
        the payload wasn't altered *after* creation. Never wired into
        :meth:`approve`/:meth:`reject`: those stay on ``payload_hash`` alone, per
        the Sprint 8 reasoning (a 5-minute task VC cannot span an hours-to-days
        human review window).
        """
        agent_id = _ACTION_AGENT_ID.get(action_type, agent_label)
        if "proposal" not in mutation_kinds(agent_id):
            # Registry/code drift, not a business-rule refusal — the caller
            # (an agent's own code) chose to propose an action_type its
            # AgentDescriptor doesn't declare "proposal" capability for. See
            # agent_registry.AgentDescriptor.mutations.
            raise RuntimeError(
                f"Agent {agent_id!r} is not declared 'proposal'-capable in "
                f"agent_registry, but create_proposal was called for "
                f"action_type {action_type!r}."
            )
        proposal_id = uuid.uuid4()
        await require_task_vc(
            agent_id=agent_id,
            transaction_id=str(proposal_id),
            operation=f"{action_type}.create_proposal",
            payload=payload,
        )
        proposal = AgentActionProposal(
            id=proposal_id,
            agent_label=agent_label,
            action_type=action_type,
            payload=payload,
            payload_hash=payload_hash(payload),
            triggered_by=triggered_by,
            rationale=rationale,
            status=ProposalStatus.PROPOSED,
        )
        self._session.add(proposal)
        await self._session.flush()  # persist the row before notify_reviewers'
        # resource_id=proposal.id reference (id is already known — set explicitly
        # above for require_task_vc — but the row itself must exist in the DB).
        # Notify reviewers who can release this action class (inventory:adjust for
        # a stock adjustment, finance:reconcile for a reconciliation match), except
        # whoever triggered the agent. Enqueue-only.
        await notify_reviewers(
            self._session,
            permission=_ACTION_NOTIFY_PERMISSION.get(
                action_type, Permission.INVENTORY_ADJUST
            ),
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
        self,
        proposal_id: uuid.UUID,
        current_user: User,
        *,
        expected_action_type: str,
    ) -> AgentActionProposal:
        """Release a pending proposal: apply its write, exactly once, mark APPLIED.

        ``expected_action_type`` binds this call to one action class — the router
        endpoint that gates authority (e.g. ``inventory:adjust`` vs.
        ``finance:reconcile``) passes the action type *it* is authorized for, so a
        reviewer holding only one domain permission can never approve a proposal
        of a different, unrelated action type by guessing its id (see
        ``routers/proposals.py``'s split-endpoint rationale).

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
        if proposal.action_type != expected_action_type:
            raise ForbiddenError(
                f"Proposal action_type {proposal.action_type!r} does not match "
                f"this endpoint ({expected_action_type!r})"
            )
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

        # Integrity check: the payload must be byte-for-byte what the maker
        # proposed. A proposal can sit PROPOSED for hours or days awaiting a
        # human, so this — not a short-TTL task-scoped credential — is the right
        # tamper check for this window; see docs on why validate_task_vc isn't
        # used here (5-minute TTL, meant for an immediate issue-then-write, not a
        # human-review queue).
        if proposal.payload_hash is not None and payload_hash(payload) != proposal.payload_hash:
            raise ForbiddenError(
                "Proposal payload has changed since it was proposed — refusing to apply"
            )

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
        self,
        proposal_id: uuid.UUID,
        current_user: User,
        *,
        expected_action_type: str,
    ) -> AgentActionProposal:
        """Reject a pending proposal (no write). Reviewer must differ from requester.

        ``expected_action_type`` — see :meth:`approve`'s docstring; prevents a
        reviewer authorized for one action class from deciding a different one.
        """
        proposal = await self._get_for_update(proposal_id)
        if proposal.action_type != expected_action_type:
            raise ForbiddenError(
                f"Proposal action_type {proposal.action_type!r} does not match "
                f"this endpoint ({expected_action_type!r})"
            )
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

        if action_type == ACTION_RECONCILIATION_MATCH:
            from src.domains.intelligence.schemas import (  # noqa: PLC0415
                ReconciliationMatch,
            )
            from src.domains.intelligence.services.reconciliation_service import (  # noqa: PLC0415
                apply_confirmed_match,
            )

            match = ReconciliationMatch.model_validate(payload)
            occurred_at = datetime.fromisoformat(payload["occurred_at"])
            payment = await apply_confirmed_match(self._session, match, occurred_at)
            if payment is None:
                # The invoice was already fully settled by the time this proposal
                # was released (e.g. paid another way while it sat pending review).
                raise UnprocessableError(
                    "Cannot apply proposal: invoice already settled"
                )
            return str(payment.id)

        raise UnprocessableError(f"Unknown action_type {action_type!r}")
