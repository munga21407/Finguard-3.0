"""
Tests for vault transfers (internal treasury movements) and per-vault balances.

Covers:
  * a transfer with a fee creates one VaultTransfer + one Expense(vault=source,
    category="Transfer fee") and links fee_expense_id;
  * get_vault_balances reflects source −(amount+fee), destination +amount, and the
    total cash position equals Σ payments − Σ expenses (transfers net to zero);
  * from_vault == to_vault is rejected at the schema layer.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from src.domains.finance.models import Expense, VaultTransfer
from src.domains.finance.schemas import VaultTransferCreate
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


def test_same_vault_transfer_is_rejected() -> None:
    with pytest.raises(ValidationError):
        VaultTransferCreate(
            from_vault=VaultType.MPESA,
            to_vault=VaultType.MPESA,
            amount=Decimal("100"),
            occurred_at=datetime.now(UTC),
        )


@pytest.mark.asyncio
async def test_transfer_with_fee_books_expense_and_links_it() -> None:
    user = _fake_user()
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
async def test_vault_balances_reflect_transfer_and_fee() -> None:
    user = _fake_user()

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
async def test_feeless_transfer_is_net_zero() -> None:
    user = _fake_user()
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
