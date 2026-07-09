"""Invoice resend — re-email an already-issued invoice (status unchanged)."""
from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import UnprocessableError
from src.domains.finance.models import Invoice
from src.domains.finance.schemas import InvoiceCreate
from src.domains.finance.service import FinanceService
from src.domains.identity.models import User, UserRole
from src.domains.notifications.models import EmailOutbox


def _user() -> User:
    return User(
        id=uuid.uuid4(), email=f"u-{uuid.uuid4().hex[:8]}@fg.local",
        hashed_password="x", full_name="U", role=UserRole.ACCOUNTANT,
        is_active=True, is_verified=True,
    )


async def _invoice(svc: FinanceService, customer_id: str) -> Invoice:
    return await svc.create_invoice(
        InvoiceCreate(
            customer_id=uuid.UUID(customer_id),
            invoice_number=f"INV-{uuid.uuid4().hex[:10].upper()}",
            subtotal=Decimal("500"), tax=Decimal("0"),
        )
    )


@pytest.mark.asyncio
async def test_resend_issued_invoice_enqueues_fresh_email(
    db_session: AsyncSession, seed_customer: str
) -> None:
    svc = FinanceService(db_session)
    inv = await _invoice(svc, seed_customer)
    await svc.send_invoice(inv.id, _user())        # DRAFT → SENT (+ first email)
    await svc.resend_invoice(inv.id, _user())      # resend

    rows = (
        await db_session.execute(
            select(EmailOutbox).where(EmailOutbox.template == "invoice_issued")
        )
    ).scalars().all()
    # One from send + one from resend, both to this invoice.
    keys = [r.idempotency_key for r in rows if str(inv.id) in r.idempotency_key]
    assert any(k.startswith("invoice_sent:") for k in keys)
    assert any(k.startswith("invoice_resent:") for k in keys)


@pytest.mark.asyncio
async def test_cannot_resend_a_draft(db_session: AsyncSession, seed_customer: str) -> None:
    svc = FinanceService(db_session)
    inv = await _invoice(svc, seed_customer)   # still DRAFT
    with pytest.raises(UnprocessableError):
        await svc.resend_invoice(inv.id, _user())
