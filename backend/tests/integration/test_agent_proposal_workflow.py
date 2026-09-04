"""Human-in-the-loop approval of agent-proposed stock adjustments.

Covers the maker-checker contract on the agentic side: an agent proposal is inert
until released (no stock change), only a *different* human may approve it (strict
segregation of duties), approval applies the write exactly once, and the state
machine forbids re-deciding a settled proposal.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import ForbiddenError, UnprocessableError
from src.domains.identity.models import User, UserRole
from src.domains.intelligence import proposal_service
from src.domains.intelligence.models import ProposalStatus
from src.domains.intelligence.proposal_service import (
    ACTION_STOCK_ADJUSTMENT,
    ProposalService,
)
from src.domains.inventory.schemas import InventoryMovementCreate, ProductCreate
from src.domains.inventory.service import InventoryService
from src.domains.inventory.types import MovementReason, MovementType, UnitOfMeasure
from src.domains.notifications.models import EmailOutbox


def _user(role: UserRole = UserRole.MANAGER) -> User:
    return User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
        full_name="reviewer",
        role=role,
        is_active=True,
        is_verified=True,
        created_at=datetime.now(UTC),
    )


async def _persisted_user(db: AsyncSession, role: UserRole = UserRole.MANAGER) -> User:
    """A user saved to the DB — needed when the flow writes an audit row whose
    ``actor_id`` has a FK to ``users`` (i.e. when an approval actually applies)."""
    user = _user(role)
    db.add(user)
    await db.commit()
    return user


async def _product_with_stock(db: AsyncSession, on_hand: str = "10"):
    svc = InventoryService(db)
    product = await svc.create_product(
        ProductCreate(
            sku=f"SKU-{uuid.uuid4().hex[:10]}",
            name="Widget",
            unit=UnitOfMeasure.EACH,
            cost_price=Decimal("10.00"),
            selling_price=Decimal("15.00"),
            reorder_level=Decimal("2"),
            reorder_quantity=Decimal("5"),
        )
    )
    await svc.record_movement(
        product.id,
        InventoryMovementCreate(
            movement_type=MovementType.RECEIPT,
            quantity=Decimal(on_hand),
            unit_cost=Decimal("10.00"),
            reason=MovementReason.PURCHASE,
        ),
    )
    return product


def _adjustment_payload(product_id: uuid.UUID, delta: str = "5") -> dict:
    return {
        "product_ref": str(product_id),
        "movement_type": MovementType.ADJUSTMENT.value,
        "quantity": float(delta),
        "reason": MovementReason.CORRECTION.value,
        "unit_cost": None,
        "note": "stock-take correction",
    }


@pytest.mark.asyncio
async def test_proposal_is_pending_with_no_stock_change(db_session: AsyncSession) -> None:
    product = await _product_with_stock(db_session, on_hand="10")
    svc = ProposalService(db_session)

    proposal = await svc.create_proposal(
        agent_label="k_stockkeeper",
        action_type=ACTION_STOCK_ADJUSTMENT,
        payload=_adjustment_payload(product.id, "5"),
        triggered_by=uuid.uuid4(),
    )

    assert proposal.status is ProposalStatus.PROPOSED
    assert proposal.reviewed_by is None
    # No write happened — on-hand is still the initial 10.
    level = await InventoryService(db_session).get_stock_level(product.id)
    assert level.quantity_on_hand == Decimal("10")


@pytest.mark.asyncio
async def test_approve_applies_adjustment_once(db_session: AsyncSession) -> None:
    product = await _product_with_stock(db_session, on_hand="10")
    svc = ProposalService(db_session)
    requester = uuid.uuid4()
    reviewer = await _persisted_user(db_session)

    proposal = await svc.create_proposal(
        agent_label="k_stockkeeper",
        action_type=ACTION_STOCK_ADJUSTMENT,
        payload=_adjustment_payload(product.id, "5"),
        triggered_by=requester,
    )
    applied = await svc.approve(
        proposal.id, reviewer, expected_action_type=ACTION_STOCK_ADJUSTMENT
    )

    assert applied.status is ProposalStatus.APPLIED
    assert applied.reviewed_by == reviewer.id
    assert applied.applied_ref
    level = await InventoryService(db_session).get_stock_level(product.id)
    assert level.quantity_on_hand == Decimal("15")  # 10 + 5, exactly once

    # Re-approving a settled proposal is refused by the state machine.
    with pytest.raises(UnprocessableError):
        await svc.approve(
            proposal.id, _user(), expected_action_type=ACTION_STOCK_ADJUSTMENT
        )
    level_again = await InventoryService(db_session).get_stock_level(product.id)
    assert level_again.quantity_on_hand == Decimal("15")


@pytest.mark.asyncio
async def test_requester_cannot_approve_own_proposal(db_session: AsyncSession) -> None:
    product = await _product_with_stock(db_session)
    svc = ProposalService(db_session)
    requester = _user()

    proposal = await svc.create_proposal(
        agent_label="k_stockkeeper",
        action_type=ACTION_STOCK_ADJUSTMENT,
        payload=_adjustment_payload(product.id, "5"),
        triggered_by=requester.id,
    )
    with pytest.raises(ForbiddenError):
        await svc.approve(
            proposal.id, requester, expected_action_type=ACTION_STOCK_ADJUSTMENT
        )

    # Still pending, no write.
    level = await InventoryService(db_session).get_stock_level(product.id)
    assert level.quantity_on_hand == Decimal("10")


@pytest.mark.asyncio
async def test_reject_leaves_stock_untouched(db_session: AsyncSession) -> None:
    product = await _product_with_stock(db_session)
    svc = ProposalService(db_session)

    proposal = await svc.create_proposal(
        agent_label="k_stockkeeper",
        action_type=ACTION_STOCK_ADJUSTMENT,
        payload=_adjustment_payload(product.id, "-4"),
        triggered_by=uuid.uuid4(),
    )
    rejected = await svc.reject(
        proposal.id, _user(), expected_action_type=ACTION_STOCK_ADJUSTMENT
    )

    assert rejected.status is ProposalStatus.REJECTED
    level = await InventoryService(db_session).get_stock_level(product.id)
    assert level.quantity_on_hand == Decimal("10")

    # A rejected proposal cannot then be approved.
    with pytest.raises(UnprocessableError):
        await svc.approve(
            proposal.id, _user(), expected_action_type=ACTION_STOCK_ADJUSTMENT
        )


@pytest.mark.asyncio
async def test_node_helper_queues_adjustment_instead_of_applying(
    db_session: AsyncSession,
) -> None:
    """Agent K's gating helper routes an ADJUSTMENT to the queue, not an inline write."""
    from src.domains.intelligence.services.stockkeeper_service import (
        _queue_adjustment_proposal,
    )

    product = await _product_with_stock(db_session, on_hand="10")
    action = {
        "product_ref": str(product.id),
        "movement_type": "adjustment",
        "quantity": 5,
        "reason": MovementReason.CORRECTION.value,
    }
    result = await _queue_adjustment_proposal(
        db_session, action, "adjustment", uuid.uuid4(), cove_verify=False
    )

    assert result["status"] == "pending_approval"
    assert result["proposal_id"]
    # No inline write — on-hand unchanged until a human approves.
    level = await InventoryService(db_session).get_stock_level(product.id)
    assert level.quantity_on_hand == Decimal("10")


@pytest.mark.asyncio
async def test_node_helper_does_not_queue_a_rejected_adjustment(
    db_session: AsyncSession,
) -> None:
    """An adjustment the guard rejects (zero delta) is surfaced, never queued."""
    from src.domains.intelligence.services.stockkeeper_service import (
        _queue_adjustment_proposal,
    )

    product = await _product_with_stock(db_session)
    action = {
        "product_ref": str(product.id),
        "movement_type": "adjustment",
        "quantity": 0,  # adjustment delta must be non-zero → rejected by the guard
        "reason": MovementReason.CORRECTION.value,
    }
    result = await _queue_adjustment_proposal(
        db_session, action, "adjustment", None, cove_verify=False
    )

    assert result["status"] == "rejected"
    pending = await ProposalService(db_session).list_pending()
    assert all(p.payload.get("product_ref") != str(product.id) for p in pending)


@pytest.mark.asyncio
async def test_create_proposal_notifies_adjust_reviewers(db_session: AsyncSession) -> None:
    """Submitting an agent proposal emails users who can release it (inventory:
    adjust), excluding whoever triggered the agent."""
    reviewer = await _persisted_user(db_session, UserRole.MANAGER)
    product = await _product_with_stock(db_session)

    proposal = await ProposalService(db_session).create_proposal(
        agent_label="k_stockkeeper",
        action_type=ACTION_STOCK_ADJUSTMENT,
        payload=_adjustment_payload(product.id, "5"),
        triggered_by=uuid.uuid4(),   # some non-reviewer requester
        rationale="stock-take variance",
    )

    row = (
        await db_session.execute(
            select(EmailOutbox).where(
                EmailOutbox.idempotency_key == f"proposal_review:{proposal.id}:{reviewer.id}"
            )
        )
    ).scalar_one_or_none()
    assert row is not None
    assert row.template == "approval_needed"
    assert row.to_email == reviewer.email


# ── Task-scoped VC on proposal *creation* (P1 of "Task-scoped VC end-to-end",
# audit/defense-in-depth — never wired into approve()/reject(), see
# create_proposal's own docstring) ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_proposal_mints_a_task_scoped_vc(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    product = await _product_with_stock(db_session)
    calls: list[dict[str, object]] = []

    async def fake_require(**kwargs: object) -> None:
        calls.append(kwargs)
    monkeypatch.setattr(proposal_service, "require_task_vc", fake_require)

    proposal = await ProposalService(db_session).create_proposal(
        agent_label="k_stockkeeper",
        action_type=ACTION_STOCK_ADJUSTMENT,
        payload=_adjustment_payload(product.id, "5"),
        triggered_by=uuid.uuid4(),
    )

    assert len(calls) == 1
    # agent_id is the registry id ("K"), not the display label — same
    # _ACTION_AGENT_ID mapping _issue_decision_vc uses for approve/reject.
    assert calls[0]["agent_id"] == "K"
    assert calls[0]["operation"] == "stock.adjustment.create_proposal"
    assert calls[0]["transaction_id"] == str(proposal.id)


async def _fail_if_task_vc_called(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fail_if_called(**_kwargs: object) -> None:
        raise AssertionError("require_task_vc must not be called here")
    monkeypatch.setattr(proposal_service, "require_task_vc", fail_if_called)


@pytest.mark.asyncio
async def test_approve_never_calls_require_task_vc(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Hard constraint: task VCs never gate approve() — it stays on
    payload_hash alone (a 5-minute TTL cannot span an hours-to-days review).
    require_task_vc is patched to a no-op for creation (already covered by
    test_create_proposal_mints_a_task_scoped_vc above) then made to fail loudly
    for the approve() call that follows."""
    product = await _product_with_stock(db_session)
    reviewer = await _persisted_user(db_session, UserRole.MANAGER)

    async def noop(**_kwargs: object) -> None:
        return None
    monkeypatch.setattr(proposal_service, "require_task_vc", noop)

    proposal = await ProposalService(db_session).create_proposal(
        agent_label="k_stockkeeper",
        action_type=ACTION_STOCK_ADJUSTMENT,
        payload=_adjustment_payload(product.id, "5"),
        triggered_by=uuid.uuid4(),
    )

    await _fail_if_task_vc_called(monkeypatch)
    approved = await ProposalService(db_session).approve(
        proposal.id, reviewer, expected_action_type=ACTION_STOCK_ADJUSTMENT
    )
    assert approved.status is ProposalStatus.APPLIED


@pytest.mark.asyncio
async def test_reject_never_calls_require_task_vc(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    product = await _product_with_stock(db_session)
    reviewer = await _persisted_user(db_session, UserRole.MANAGER)

    async def noop(**_kwargs: object) -> None:
        return None
    monkeypatch.setattr(proposal_service, "require_task_vc", noop)

    proposal = await ProposalService(db_session).create_proposal(
        agent_label="k_stockkeeper",
        action_type=ACTION_STOCK_ADJUSTMENT,
        payload=_adjustment_payload(product.id, "5"),
        triggered_by=uuid.uuid4(),
    )

    await _fail_if_task_vc_called(monkeypatch)
    rejected = await ProposalService(db_session).reject(
        proposal.id, reviewer, expected_action_type=ACTION_STOCK_ADJUSTMENT
    )
    assert rejected.status is ProposalStatus.REJECTED


# ── Trust protocol: payload integrity + action-type binding (remediation A1) ──

@pytest.mark.asyncio
async def test_approve_rejects_tampered_payload(db_session: AsyncSession) -> None:
    """A proposal's payload_hash pins it at creation — an altered payload (e.g. a
    manual DB edit) must be refused at approval, not silently replayed."""
    product = await _product_with_stock(db_session, on_hand="10")
    svc = ProposalService(db_session)
    reviewer = await _persisted_user(db_session)

    proposal = await svc.create_proposal(
        agent_label="k_stockkeeper",
        action_type=ACTION_STOCK_ADJUSTMENT,
        payload=_adjustment_payload(product.id, "5"),
        triggered_by=uuid.uuid4(),
    )
    assert proposal.payload_hash  # set at creation

    # Simulate the payload being altered after the maker proposed it.
    proposal.payload = {**proposal.payload, "quantity": 999.0}
    await db_session.commit()

    with pytest.raises(ForbiddenError, match="payload has changed"):
        await svc.approve(
            proposal.id, reviewer, expected_action_type=ACTION_STOCK_ADJUSTMENT
        )
    level = await InventoryService(db_session).get_stock_level(product.id)
    assert level.quantity_on_hand == Decimal("10")  # untouched


@pytest.mark.asyncio
async def test_approve_rejects_mismatched_action_type(db_session: AsyncSession) -> None:
    """A reviewer authorized for one action class cannot approve a proposal of a
    different class through the wrong endpoint's service call."""
    from src.domains.intelligence.proposal_service import ACTION_RECONCILIATION_MATCH

    product = await _product_with_stock(db_session, on_hand="10")
    svc = ProposalService(db_session)
    reviewer = await _persisted_user(db_session)

    proposal = await svc.create_proposal(
        agent_label="k_stockkeeper",
        action_type=ACTION_STOCK_ADJUSTMENT,
        payload=_adjustment_payload(product.id, "5"),
        triggered_by=uuid.uuid4(),
    )

    with pytest.raises(ForbiddenError, match="does not match"):
        await svc.approve(
            proposal.id, reviewer, expected_action_type=ACTION_RECONCILIATION_MATCH
        )
    level = await InventoryService(db_session).get_stock_level(product.id)
    assert level.quantity_on_hand == Decimal("10")  # untouched
