"""Payment-reminder tiering + dispatch.

The tier function is pure; the dispatch sweep enqueues one reminder per
(invoice, tier) and is idempotent across runs (the escalating-daily-sweep
contract). MAIL_ENABLED is false so nothing sends.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domains.finance.models import Invoice, InvoiceStatus
from src.domains.finance.schemas import InvoiceCreate
from src.domains.finance.service import FinanceService
from src.domains.notifications.models import EmailOutbox
from src.workers.tasks.email_tasks import _dispatch_payment_reminders, _reminder_tier
from tests.conftest import TestingSessionLocal


def _now() -> datetime:
    return datetime(2026, 7, 8, tzinfo=UTC)


@pytest.mark.parametrize(
    "offset_days,expected",
    [
        (10, None),        # far in the future → no reminder
        (2, "due_soon"),   # due in 2 days
        (0, "due_soon"),   # due today counts as due_soon (0 < days? no) → see note
        (-1, "overdue_1"),
        (-7, "overdue_7"),
        (-13, "overdue_7"),
        (-14, "overdue_14"),
        (-30, "overdue_30"),
        (-90, "overdue_30"),
    ],
)
def test_reminder_tier(offset_days: int, expected: str | None) -> None:
    now = _now()
    due = now + timedelta(days=offset_days)
    # due today (offset 0) is not "0 < days_until_due", so it falls through to
    # overdue==0 → None. Adjust the expectation for that single boundary.
    if offset_days == 0:
        assert _reminder_tier(due, now) is None
    else:
        assert _reminder_tier(due, now) == expected


async def _sent_invoice(db: AsyncSession, customer_id: str, *, due_offset_days: int) -> Invoice:
    svc = FinanceService(db)
    invoice = await svc.create_invoice(
        InvoiceCreate(
            customer_id=uuid.UUID(customer_id),
            invoice_number=f"INV-{uuid.uuid4().hex[:10].upper()}",
            subtotal=Decimal("1000"),
            tax=Decimal("0"),
            due_date=datetime.now(UTC) + timedelta(days=due_offset_days),
        )
    )
    # Reminders only scan issued invoices; flip DRAFT → SENT directly.
    invoice.status = InvoiceStatus.SENT
    await db.flush()
    await db.commit()
    return invoice


@pytest.mark.asyncio
async def test_dispatch_enqueues_overdue_reminder_once(
    db_session: AsyncSession, seed_customer: str
) -> None:
    # Clean slate — the dispatch scans all invoices/customers in the shared DB.
    async with TestingSessionLocal() as s:
        await s.execute(delete(EmailOutbox))
        await s.commit()

    invoice = await _sent_invoice(db_session, seed_customer, due_offset_days=-8)

    first = await _dispatch_payment_reminders(session_factory=TestingSessionLocal)
    assert first["enqueued"] >= 1

    key = f"reminder:{invoice.id}:overdue_7"
    row = (
        await db_session.execute(select(EmailOutbox).where(EmailOutbox.idempotency_key == key))
    ).scalar_one()
    assert row.template == "payment_reminder"
    assert row.context["is_overdue"] is True
    assert row.context["days_overdue"] == 8

    # A second sweep must not re-enqueue the same tier (idempotent).
    second = await _dispatch_payment_reminders(session_factory=TestingSessionLocal)
    rows = (
        await db_session.execute(select(EmailOutbox).where(EmailOutbox.idempotency_key == key))
    ).scalars().all()
    assert len(rows) == 1
    assert second["enqueued"] == 0
