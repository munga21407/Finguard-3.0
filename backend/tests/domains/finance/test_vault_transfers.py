"""
Tests for vault transfers (internal treasury movements) and per-vault balances.

Covers:
  * a transfer with a fee creates one VaultTransfer + one Expense(vault=source,
    category="Transfer fee") and links fee_expense_id;
  * get_vault_balances reflects source −(amount+fee), destination +amount, and the
    total cash position equals Σ payments − Σ expenses (transfers net to zero);
  * from_vault == to_vault is rejected at the schema layer;
  * a transfer that exceeds the source vault balance is rejected (overdraw guard);
  * a transfer fee does NOT burn a category budget (financing cost, not opex).
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from src.core.exceptions import UnprocessableError
from src.domains.finance.models import Budget, Expense, VaultTransfer
from src.domains.finance.schemas import BudgetCreate, InvoiceCreate, VaultTransferCreate
from src.domains.finance.service import FinanceService
from src.domains.finance.types import VaultType
from src.domains.identity.models import User, UserRole
from tests.conftest import TestingSessionLocal


def _fake_user() -> User:
    return User(
        id=uuid.uuid4(),
        email=f"treasurer-{uuid.uuid4().hex[:8]}@finguard.local",
        hashed_password="x",
        full_name="Treasurer",
        role=UserRole.ACCOUNTANT,
        is_active=True,
        is_verified=True,
    )


async def _fund_vault(customer_id: str, vault: VaultType, amount: str) -> None:
    """Give a vault a positive balance by settling a fresh invoice on it."""
    async with TestingSessionLocal() as session:
        svc = FinanceService(session)
        invoice = await svc.create_invoice(
            InvoiceCreate(
                customer_id=uuid.UUID(customer_id),
                invoice_number=f"INV-{uuid.uuid4().hex[:10].upper()}",
                subtotal=Decimal(amount),
                tax=Decimal("0"),
            )
        )
        await svc.mark_invoice_paid(invoice.id, vault=vault)


def test_same_vault_transfer_is_rejected() -> None:
    with pytest.raises(ValidationError):
        VaultTransferCreate(
            from_vault=VaultType.MPESA,
            to_vault=VaultType.MPESA,
            amount=Decimal("100"),
            occurred_at=datetime.now(UTC),
        )


@pytest.mark.asyncio
async def test_transfer_with_fee_books_expense_and_links_it(seed_customer: str) -> None:
    user = _fake_user()
    await _fund_vault(seed_customer, VaultType.MPESA, "60000")

    async with TestingSessionLocal() as session:
        transfer = await FinanceService(session).create_vault_transfer(
            VaultTransferCreate(
                from_vault=VaultType.MPESA,
                to_vault=VaultType.BANK,
                amount=Decimal("50000"),
                fee=Decimal("200"),
                occurred_at=datetime.now(UTC),
            ),
            user,
        )
        transfer_id = transfer.id

    async with TestingSessionLocal() as session:
        transfer = await session.get(VaultTransfer, transfer_id)
        assert transfer is not None
        assert transfer.fee_expense_id is not None

        fee_expense = await session.get(Expense, transfer.fee_expense_id)
        assert fee_expense is not None
        assert fee_expense.category == "Transfer fee"
        assert fee_expense.amount == Decimal("200")
        assert fee_expense.vault == VaultType.MPESA


@pytest.mark.asyncio
async def test_vault_balances_reflect_transfer_and_fee(seed_customer: str) -> None:
    user = _fake_user()
    await _fund_vault(seed_customer, VaultType.MPESA, "60000")

    async with TestingSessionLocal() as session:
        before = await FinanceService(session).get_vault_balances()
    before_by = {b.vault: b.balance for b in before.balances}

    async with TestingSessionLocal() as session:
        await FinanceService(session).create_vault_transfer(
            VaultTransferCreate(
                from_vault=VaultType.MPESA,
                to_vault=VaultType.BANK,
                amount=Decimal("50000"),
                fee=Decimal("200"),
                occurred_at=datetime.now(UTC),
            ),
            user,
        )

    async with TestingSessionLocal() as session:
        after = await FinanceService(session).get_vault_balances()
    after_by = {b.vault: b.balance for b in after.balances}

    # Source down by amount + fee; destination up by amount.
    assert after_by[VaultType.MPESA] == before_by[VaultType.MPESA] - Decimal("50200")
    assert after_by[VaultType.BANK] == before_by[VaultType.BANK] + Decimal("50000")
    # Total cash position drops only by the fee (the transfer itself is net-zero).
    assert after.total == before.total - Decimal("200")

    # Every vault is always represented.
    assert {b.vault for b in after.balances} == set(VaultType)


@pytest.mark.asyncio
async def test_feeless_transfer_is_net_zero(seed_customer: str) -> None:
    user = _fake_user()
    await _fund_vault(seed_customer, VaultType.CASH, "20000")

    async with TestingSessionLocal() as session:
        before = await FinanceService(session).get_vault_balances()

    async with TestingSessionLocal() as session:
        transfer = await FinanceService(session).create_vault_transfer(
            VaultTransferCreate(
                from_vault=VaultType.CASH,
                to_vault=VaultType.BANK,
                amount=Decimal("10000"),
                occurred_at=datetime.now(UTC),
            ),
            user,
        )
        assert transfer.fee_expense_id is None

    async with TestingSessionLocal() as session:
        after = await FinanceService(session).get_vault_balances()

    assert after.total == before.total  # no fee → total cash unchanged


@pytest.mark.asyncio
async def test_overdraw_is_rejected(seed_customer: str) -> None:
    """You can't move more money than the source vault holds (amount + fee)."""
    user = _fake_user()
    await _fund_vault(seed_customer, VaultType.MPESA, "1000")

    async with TestingSessionLocal() as session:
        with pytest.raises(UnprocessableError):
            await FinanceService(session).create_vault_transfer(
                VaultTransferCreate(
                    from_vault=VaultType.MPESA,
                    to_vault=VaultType.BANK,
                    amount=Decimal("1000"),
                    fee=Decimal("50"),  # 1050 > 1000 balance
                    occurred_at=datetime.now(UTC),
                ),
                user,
            )


@pytest.mark.asyncio
async def test_transfer_fee_does_not_burn_budget(seed_customer: str) -> None:
    """A transfer fee is a financing cost — it must not burn a category budget."""
    user = _fake_user()
    await _fund_vault(seed_customer, VaultType.MPESA, "60000")

    async with TestingSessionLocal() as session:
        budget = await FinanceService(session).create_budget(
            BudgetCreate(
                name="Bank fees",
                category="Transfer fee",  # same category the fee expense uses
                amount=Decimal("1000"),
                period_start=datetime.now(UTC) - timedelta(days=1),
                period_end=datetime.now(UTC) + timedelta(days=30),
            )
        )
        budget_id = budget.id

    async with TestingSessionLocal() as session:
        await FinanceService(session).create_vault_transfer(
            VaultTransferCreate(
                from_vault=VaultType.MPESA,
                to_vault=VaultType.BANK,
                amount=Decimal("50000"),
                fee=Decimal("200"),
                occurred_at=datetime.now(UTC),
            ),
            user,
        )

    async with TestingSessionLocal() as session:
        refreshed = await session.get(Budget, budget_id)
        assert refreshed is not None
        assert refreshed.spent == Decimal("0")  # fee did NOT burn the budget
