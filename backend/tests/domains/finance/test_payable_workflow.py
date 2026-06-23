"""Accounts-payable approval workflow (maker-checker state machine on expenses).

Covers the legal/illegal approval transitions, segregation of duties (the
submitter cannot review their own payable), and the deferral contract: a payable
burns budget and lands in the vault outflow only once it is APPROVED — never
while it is still PENDING_REVIEW.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from src.core.exceptions import ForbiddenError, UnprocessableError
from src.domains.finance.models import Budget, ExpenseApprovalStatus
from src.domains.finance.schemas import ExpenseCreate, PayableCreate
from src.domains.finance.service import FinanceService
from src.domains.finance.types import VaultType
from src.domains.identity.models import User, UserRole
from tests.conftest import TestingSessionLocal


def _user() -> User:
    return User(
        id=uuid.uuid4(),
        email=f"ap-{uuid.uuid4().hex[:8]}@finguard.local",
        hashed_password="x",
        full_name="AP User",
        role=UserRole.MANAGER,
        is_active=True,
        is_verified=True,
    )


async def _seed_budget(category: str, amount: str = "10000") -> None:
    now = datetime.now(UTC)
    async with TestingSessionLocal() as session:
        session.add(
            Budget(
                name=f"{category}-budget",
                category=category,
                amount=Decimal(amount),
                spent=Decimal("0"),
                period_start=now - timedelta(days=1),
                period_end=now + timedelta(days=30),
            )
        )
        await session.commit()


async def _budget_spent(category: str) -> Decimal:
    async with TestingSessionLocal() as session:
        budgets = await FinanceService(session).list_budgets()
    return next(b.spent for b in budgets if b.category == category)


def _payable(category: str) -> PayableCreate:
    return PayableCreate(category=category, amount=Decimal("500"), vault=VaultType.BANK)


@pytest.mark.asyncio
async def test_create_payable_is_pending_with_no_budget_burn() -> None:
    category = f"cat-{uuid.uuid4().hex[:6]}"
    await _seed_budget(category)
    async with TestingSessionLocal() as session:
        expense = await FinanceService(session).create_payable(_payable(category), _user())
    assert expense.approval_status == ExpenseApprovalStatus.PENDING_REVIEW
    assert expense.submitted_by is not None
    # Deferred: a pending payable must not consume budget.
    assert await _budget_spent(category) == Decimal("0")


@pytest.mark.asyncio
async def test_approval_burns_budget_once() -> None:
    category = f"cat-{uuid.uuid4().hex[:6]}"
    await _seed_budget(category)
    submitter, reviewer = _user(), _user()
    async with TestingSessionLocal() as session:
        expense = await FinanceService(session).create_payable(_payable(category), submitter)
    async with TestingSessionLocal() as session:
        approved = await FinanceService(session).transition_payable(
            expense.id, reviewer, target=ExpenseApprovalStatus.APPROVED
        )
    assert approved.approval_status == ExpenseApprovalStatus.APPROVED
    assert approved.reviewed_by == reviewer.id
    assert approved.reviewed_at is not None
    assert await _budget_spent(category) == Decimal("500")


@pytest.mark.asyncio
async def test_submitter_cannot_approve_own_payable() -> None:
    category = f"cat-{uuid.uuid4().hex[:6]}"
    submitter = _user()
    async with TestingSessionLocal() as session:
        expense = await FinanceService(session).create_payable(_payable(category), submitter)
    async with TestingSessionLocal() as session:
        with pytest.raises(ForbiddenError):
            await FinanceService(session).transition_payable(
                expense.id, submitter, target=ExpenseApprovalStatus.APPROVED
            )


@pytest.mark.asyncio
async def test_reject_then_cannot_be_approved() -> None:
    category = f"cat-{uuid.uuid4().hex[:6]}"
    await _seed_budget(category)
    submitter, reviewer = _user(), _user()
    async with TestingSessionLocal() as session:
        expense = await FinanceService(session).create_payable(_payable(category), submitter)
    async with TestingSessionLocal() as session:
        rejected = await FinanceService(session).transition_payable(
            expense.id, reviewer, target=ExpenseApprovalStatus.REJECTED
        )
    assert rejected.approval_status == ExpenseApprovalStatus.REJECTED
    # REJECTED is terminal — no further transition is legal.
    async with TestingSessionLocal() as session:
        with pytest.raises(UnprocessableError):
            await FinanceService(session).transition_payable(
                expense.id, reviewer, target=ExpenseApprovalStatus.APPROVED
            )
    # And a rejected payable never burned budget.
    assert await _budget_spent(category) == Decimal("0")


@pytest.mark.asyncio
async def test_approved_can_be_scheduled() -> None:
    category = f"cat-{uuid.uuid4().hex[:6]}"
    await _seed_budget(category)
    submitter, reviewer = _user(), _user()
    async with TestingSessionLocal() as session:
        expense = await FinanceService(session).create_payable(_payable(category), submitter)
    async with TestingSessionLocal() as session:
        await FinanceService(session).transition_payable(
            expense.id, reviewer, target=ExpenseApprovalStatus.APPROVED
        )
    when = datetime.now(UTC) + timedelta(days=3)
    async with TestingSessionLocal() as session:
        scheduled = await FinanceService(session).transition_payable(
            expense.id, reviewer, target=ExpenseApprovalStatus.SCHEDULED, scheduled_for=when
        )
    assert scheduled.approval_status == ExpenseApprovalStatus.SCHEDULED
    assert scheduled.scheduled_for is not None


@pytest.mark.asyncio
async def test_cannot_skip_straight_to_scheduled() -> None:
    category = f"cat-{uuid.uuid4().hex[:6]}"
    submitter, reviewer = _user(), _user()
    async with TestingSessionLocal() as session:
        expense = await FinanceService(session).create_payable(_payable(category), submitter)
    async with TestingSessionLocal() as session:
        with pytest.raises(UnprocessableError):
            await FinanceService(session).transition_payable(
                expense.id, reviewer, target=ExpenseApprovalStatus.SCHEDULED
            )


@pytest.mark.asyncio
async def test_pending_payable_excluded_from_vault_outflow() -> None:
    """A pending payable is a proposed bill, not cash out — vault balances ignore it."""
    category = f"cat-{uuid.uuid4().hex[:6]}"
    async with TestingSessionLocal() as session:
        before = (await FinanceService(session).get_vault_balances()).balances
    before_bank = next(b.balance for b in before if b.vault == VaultType.BANK)

    async with TestingSessionLocal() as session:
        await FinanceService(session).create_payable(_payable(category), _user())

    async with TestingSessionLocal() as session:
        after = (await FinanceService(session).get_vault_balances()).balances
    after_bank = next(b.balance for b in after if b.vault == VaultType.BANK)
    assert after_bank == before_bank


@pytest.mark.asyncio
async def test_direct_create_expense_defaults_to_approved() -> None:
    """The immediate creation path keeps today's behaviour: APPROVED + budget burn."""
    category = f"cat-{uuid.uuid4().hex[:6]}"
    await _seed_budget(category)
    async with TestingSessionLocal() as session:
        expense = await FinanceService(session).create_expense(
            ExpenseCreate(category=category, amount=Decimal("300"), vault=VaultType.CASH)
        )
    assert expense.approval_status == ExpenseApprovalStatus.APPROVED
    assert await _budget_spent(category) == Decimal("300")
