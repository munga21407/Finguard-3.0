"""
Regression tests for cash-payment application.

Covers:
  * partial settlement updates amount_paid / balance_due and flips status to
    PARTIALLY_PAID, then PAID once the balance reaches zero;
  * overpayment is rejected;
  * concurrent payments against one invoice serialise via the FOR UPDATE row
    lock and cannot over-credit the invoice (lost-update prevention).
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import UnprocessableError
from src.domains.finance.models import Invoice, InvoiceStatus
from src.domains.finance.schemas import InvoiceCreate, PaymentCreate
from src.domains.finance.service import FinanceService
from src.domains.identity.models import User, UserRole
from tests.conftest import TestingSessionLocal


def _fake_user() -> User:
    return User(
        id=uuid.uuid4(),
        email=f"payer-{uuid.uuid4().hex[:8]}@finguard.local",
        hashed_password="x",
        full_name="Payer",
        role=UserRole.ACCOUNTANT,
        is_active=True,
        is_verified=True,
    )


async def _make_invoice(
    svc: FinanceService, customer_id: str, *, subtotal: str
) -> Invoice:
    return await svc.create_invoice(
        InvoiceCreate(
            customer_id=uuid.UUID(customer_id),
            invoice_number=f"INV-{uuid.uuid4().hex[:10].upper()}",
            subtotal=Decimal(subtotal),
            tax=Decimal("0"),
        )
    )


@pytest.mark.asyncio
async def test_partial_then_full_payment_transitions_status(
    db_session: AsyncSession, seed_customer: str
) -> None:
    svc = FinanceService(db_session)
    user = _fake_user()
    invoice = await _make_invoice(svc, seed_customer, subtotal="1000")
    now = datetime.now(UTC)

    # First partial payment.
    await svc.record_cash_payment(
        PaymentCreate(invoice_id=invoice.id, amount=Decimal("400"), payment_date=now), user
    )
    refreshed = await db_session.get(Invoice, invoice.id)
    assert refreshed is not None
    assert refreshed.amount_paid == Decimal("400")
    assert refreshed.balance_due == Decimal("600")
    assert refreshed.status == InvoiceStatus.PARTIALLY_PAID

    # Settle the remainder.
    await svc.record_cash_payment(
        PaymentCreate(invoice_id=invoice.id, amount=Decimal("600"), payment_date=now), user
    )
    refreshed = await db_session.get(Invoice, invoice.id)
    assert refreshed is not None
    assert refreshed.balance_due == Decimal("0")
    assert refreshed.status == InvoiceStatus.PAID
    assert refreshed.paid_at is not None


@pytest.mark.asyncio
async def test_overpayment_is_rejected(
    db_session: AsyncSession, seed_customer: str
) -> None:
    svc = FinanceService(db_session)
    user = _fake_user()
    invoice = await _make_invoice(svc, seed_customer, subtotal="500")

    with pytest.raises(UnprocessableError):
        await svc.record_cash_payment(
            PaymentCreate(
                invoice_id=invoice.id,
                amount=Decimal("501"),
                payment_date=datetime.now(UTC),
            ),
            user,
        )


@pytest.mark.asyncio
async def test_concurrent_payments_do_not_overcredit(seed_customer: str) -> None:
    # Create + commit an invoice with a balance of exactly 100 so two racing
    # payments of 100 cannot both succeed without over-crediting.
    invoice_id = uuid.uuid4()
    async with TestingSessionLocal() as session:
        svc = FinanceService(session)
        invoice = await svc.create_invoice(
            InvoiceCreate(
                customer_id=uuid.UUID(seed_customer),
                invoice_number=f"INV-{uuid.uuid4().hex[:10].upper()}",
                subtotal=Decimal("100"),
                tax=Decimal("0"),
            )
        )
        invoice_id = invoice.id

    user = _fake_user()

    async def pay() -> object:
        async with TestingSessionLocal() as session:
            svc = FinanceService(session)
            return await svc.record_cash_payment(
                PaymentCreate(
                    invoice_id=invoice_id,
                    amount=Decimal("100"),
                    payment_date=datetime.now(UTC),
                ),
                user,
            )

    results = await asyncio.gather(pay(), pay(), return_exceptions=True)

    successes = [r for r in results if not isinstance(r, Exception)]
    failures = [r for r in results if isinstance(r, Exception)]

    assert len(successes) == 1, "exactly one concurrent payment should succeed"
    assert len(failures) == 1
    assert isinstance(failures[0], UnprocessableError)

    # The invoice must be exactly settled — never over-credited.
    async with TestingSessionLocal() as session:
        final = await session.get(Invoice, invoice_id)
        assert final is not None
        assert final.amount_paid == Decimal("100")
        assert final.balance_due == Decimal("0")
        assert final.status == InvoiceStatus.PAID
