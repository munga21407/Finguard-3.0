"""Phase 1 mailing trigger: a payment-received receipt to the customer.

Both the manual-cash and agent-reconciled payment paths enqueue a receipt (keyed
on the payment id, so it can't double-send) that rides the payment transaction.
A customer without an email is skipped, never failing the payment.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domains.crm.models import Customer
from src.domains.finance.models import Invoice
from src.domains.finance.schemas import InvoiceCreate, PaymentCreate
from src.domains.finance.service import FinanceService
from src.domains.identity.models import User, UserRole
from src.domains.notifications.models import EmailOutbox
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


async def _make_invoice(svc: FinanceService, customer_id: str) -> Invoice:
    return await svc.create_invoice(
        InvoiceCreate(
            customer_id=uuid.UUID(customer_id),
            invoice_number=f"INV-{uuid.uuid4().hex[:10].upper()}",
            subtotal=Decimal("1000"),
            tax=Decimal("0"),
        )
    )


@pytest.mark.asyncio
async def test_cash_payment_enqueues_receipt(
    db_session: AsyncSession, seed_customer: str
) -> None:
    svc = FinanceService(db_session)
    invoice = await _make_invoice(svc, seed_customer)
    payment = await svc.record_cash_payment(
        PaymentCreate(invoice_id=invoice.id, amount=Decimal("400"), payment_date=datetime.now(UTC)),
        _fake_user(),
    )

    row = (
        await db_session.execute(
            select(EmailOutbox).where(EmailOutbox.idempotency_key == f"receipt:{payment.id}")
        )
    ).scalar_one()
    assert row.template == "payment_receipt"
    assert row.to_email.endswith("@example.com")     # the seeded customer's email
    assert row.context["amount"] == "400.00"
    assert row.context["invoice_number"] == invoice.invoice_number
    assert row.context["balance_due"] == "600.00"    # 1000 − 400


@pytest.mark.asyncio
async def test_customer_without_email_skips_receipt_but_payment_succeeds(
    db_session: AsyncSession,
) -> None:
    # A customer row is guaranteed to have an email by the schema, so simulate the
    # "no recipient" branch by pointing the receipt at a customer that resolves to
    # no email — here, a deleted/absent customer id on the invoice.
    async with TestingSessionLocal() as s:
        customer = Customer(name="Ghost", email=f"ghost-{uuid.uuid4().hex[:8]}@example.com")
        s.add(customer)
        await s.commit()
        customer_id = str(customer.id)

    svc = FinanceService(db_session)
    invoice = await _make_invoice(svc, customer_id)

    # Blank the customer's email to exercise the skip path.
    cust = await db_session.get(Customer, uuid.UUID(customer_id))
    assert cust is not None
    cust.email = ""
    await db_session.flush()

    payment = await svc.record_cash_payment(
        PaymentCreate(invoice_id=invoice.id, amount=Decimal("100"), payment_date=datetime.now(UTC)),
        _fake_user(),
    )

    # Payment recorded, but no receipt enqueued (no recipient).
    assert payment is not None
    row = (
        await db_session.execute(
            select(EmailOutbox).where(EmailOutbox.idempotency_key == f"receipt:{payment.id}")
        )
    ).scalar_one_or_none()
    assert row is None
