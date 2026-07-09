"""Invoice delivery + payable approval-notification email triggers.

Sending a draft invoice flips it DRAFT→SENT and enqueues an invoice email to the
customer; submitting a payable notifies every user who can approve it (finance:
approve) except the submitter. All enqueue-only, MAIL_ENABLED false (dry-run).
"""
from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import UnprocessableError
from src.domains.finance.models import InvoiceStatus
from src.domains.finance.schemas import InvoiceCreate, PayableCreate
from src.domains.finance.service import FinanceService
from src.domains.finance.types import VaultType
from src.domains.identity.models import User, UserRole
from src.domains.notifications.models import EmailOutbox
from tests.conftest import TestingSessionLocal


def _user(role: UserRole = UserRole.ACCOUNTANT) -> User:
    return User(
        id=uuid.uuid4(),
        email=f"u-{uuid.uuid4().hex[:8]}@finguard.local",
        hashed_password="x",
        full_name=f"{role.value} user",
        role=role,
        is_active=True,
        is_verified=True,
    )


async def _persist(*users: User) -> None:
    async with TestingSessionLocal() as s:
        s.add_all(list(users))
        await s.commit()


async def _emails_with_prefix(db: AsyncSession, prefix: str) -> list[EmailOutbox]:
    rows = (await db.execute(select(EmailOutbox))).scalars().all()
    return [r for r in rows if r.idempotency_key.startswith(prefix)]


# ── Invoice delivery ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_send_invoice_flips_to_sent_and_emails_customer(
    db_session: AsyncSession, seed_customer: str
) -> None:
    svc = FinanceService(db_session)
    invoice = await svc.create_invoice(
        InvoiceCreate(
            customer_id=uuid.UUID(seed_customer),
            invoice_number=f"INV-{uuid.uuid4().hex[:10].upper()}",
            subtotal=Decimal("500"),
            tax=Decimal("0"),
        )
    )
    assert invoice.status is InvoiceStatus.DRAFT

    sent = await svc.send_invoice(invoice.id, _user())
    assert sent.status is InvoiceStatus.SENT

    row = (
        await db_session.execute(
            select(EmailOutbox).where(EmailOutbox.idempotency_key == f"invoice_sent:{invoice.id}")
        )
    ).scalar_one()
    assert row.template == "invoice_issued"
    assert row.context["invoice_number"] == invoice.invoice_number


@pytest.mark.asyncio
async def test_send_non_draft_invoice_is_rejected(
    db_session: AsyncSession, seed_customer: str
) -> None:
    svc = FinanceService(db_session)
    invoice = await svc.create_invoice(
        InvoiceCreate(
            customer_id=uuid.UUID(seed_customer),
            invoice_number=f"INV-{uuid.uuid4().hex[:10].upper()}",
            subtotal=Decimal("500"),
            tax=Decimal("0"),
        )
    )
    await svc.send_invoice(invoice.id, _user())  # → SENT
    with pytest.raises(UnprocessableError):
        await svc.send_invoice(invoice.id, _user())  # already sent


# ── Payable approval notifications ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_payable_notifies_approvers_not_submitter(
    db_session: AsyncSession,
) -> None:
    submitter = _user(UserRole.ACCOUNTANT)
    manager = _user(UserRole.MANAGER)
    owner = _user(UserRole.OWNER)
    # The submitter also happens to be a manager elsewhere? No — accountant can't
    # approve, so they simply shouldn't be in the recipient set anyway.
    await _persist(submitter, manager, owner)

    svc = FinanceService(db_session)
    expense = await svc.create_payable(
        PayableCreate(category="Cloud", amount=Decimal("1200"), vault=VaultType.BANK),
        submitter,
    )

    notified = await _emails_with_prefix(db_session, f"payable_review:{expense.id}:")
    recipients = {r.to_email for r in notified}
    assert manager.email in recipients
    assert owner.email in recipients
    assert submitter.email not in recipients          # accountant can't approve
    assert all(r.template == "approval_needed" for r in notified)


@pytest.mark.asyncio
async def test_manager_submitter_is_excluded_from_own_payable(
    db_session: AsyncSession,
) -> None:
    # A manager can both submit and approve in general — but not their OWN bill.
    manager_submitter = _user(UserRole.MANAGER)
    other_manager = _user(UserRole.MANAGER)
    await _persist(manager_submitter, other_manager)

    svc = FinanceService(db_session)
    expense = await svc.create_payable(
        PayableCreate(category="Ops", amount=Decimal("300"), vault=VaultType.CASH),
        manager_submitter,
    )

    notified = await _emails_with_prefix(db_session, f"payable_review:{expense.id}:")
    recipients = {r.to_email for r in notified}
    assert other_manager.email in recipients
    assert manager_submitter.email not in recipients   # can't review their own
