"""Celery entrypoints for transactional email.

The drain logic itself lives in ``src.workers.email.flusher`` (Celery-free, so the
app can run it in-process via ``ENABLE_EMAIL_FLUSHER``); this module only wraps it
as beat-scheduled tasks. The payment-reminder sweep is Celery-only — it's a daily
cron, not a poll loop.
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.infrastructure.database.postgres import AsyncSessionLocal
from src.workers.email.flusher import flush_once as _flush_email_outbox
from src.workers.tasks.celery_app import celery_app

__all__ = ["_flush_email_outbox", "dispatch_payment_reminders", "flush_outbox"]


@celery_app.task(name="email.flush_outbox", queue="notifications")  # type: ignore[untyped-decorator]
def flush_outbox() -> dict[str, Any]:
    """Beat-scheduled drain of the email outbox. Manual run::

    celery -A src.workers.tasks.celery_app call email.flush_outbox
    """
    return asyncio.run(_flush_email_outbox())


# ── Payment reminders ─────────────────────────────────────────────────────────

def _reminder_tier(due_date: datetime, now: datetime) -> str | None:
    """The reminder tier an unpaid invoice currently qualifies for, or None.

    Thresholds are operator-tunable (``REMINDER_DUE_SOON_DAYS`` /
    ``REMINDER_OVERDUE_DAYS``). Each tier fires at most once per invoice because
    the enqueue key is ``reminder:{invoice_id}:{tier}`` — so a daily sweep
    escalates through the ladder without ever re-nagging a tier it already sent.
    """
    days_until_due = (due_date.date() - now.date()).days
    if 0 < days_until_due <= settings.REMINDER_DUE_SOON_DAYS:
        return "due_soon"
    overdue = -days_until_due
    # Highest crossed overdue threshold wins (so a daily sweep steps up the ladder).
    for threshold in sorted(settings.REMINDER_OVERDUE_DAYS, reverse=True):
        if overdue >= threshold:
            return f"overdue_{threshold}"
    return None


async def _dispatch_payment_reminders(
    session_factory: Callable[[], AsyncSession] = AsyncSessionLocal,
) -> dict[str, Any]:
    """Enqueue due-soon / overdue reminders for every unpaid, dated invoice.

    Enqueue-only + idempotency-keyed per (invoice, tier), so repeated daily runs
    never double-send. ``session_factory`` is injectable for tests.
    """
    from src.domains.crm.models import Customer  # noqa: PLC0415
    from src.domains.finance.models import Invoice, InvoiceStatus  # noqa: PLC0415
    from src.domains.notifications.models import EmailCategory  # noqa: PLC0415
    from src.domains.notifications.reviewers import unsubscribe_url  # noqa: PLC0415
    from src.domains.notifications.service import NotificationService  # noqa: PLC0415

    now = datetime.now(UTC)
    enqueued = 0

    async with session_factory() as session:
        result = await session.execute(
            select(Invoice, Customer.email, Customer.name)
            .join(Customer, Customer.id == Invoice.customer_id)
            .where(
                Invoice.status.in_(
                    (
                        InvoiceStatus.SENT,
                        InvoiceStatus.PARTIALLY_PAID,
                        InvoiceStatus.OVERDUE,
                    )
                ),
                Invoice.balance_due > 0,
                Invoice.due_date.is_not(None),
            )
        )
        svc = NotificationService(session)
        for invoice, customer_email, customer_name in result.all():
            tier = _reminder_tier(invoice.due_date, now)
            if tier is None:
                continue
            is_overdue = tier.startswith("overdue")
            days_overdue = max(0, (now.date() - invoice.due_date.date()).days)
            did = await svc.enqueue_email(
                to_email=customer_email,
                to_name=customer_name,
                subject=(
                    f"{'Overdue' if is_overdue else 'Reminder'}: invoice {invoice.invoice_number}"
                ),
                template="payment_reminder",
                context={
                    "customer_name": customer_name,
                    "invoice_number": invoice.invoice_number,
                    "currency": invoice.currency,
                    "balance_due": str(invoice.balance_due),
                    "due_date": invoice.due_date.date().isoformat(),
                    "is_overdue": is_overdue,
                    "days_overdue": days_overdue,
                    "unsubscribe_url": unsubscribe_url(customer_email, EmailCategory.REMINDER),
                },
                idempotency_key=f"reminder:{invoice.id}:{tier}",
                category=EmailCategory.REMINDER,
            )
            if did:
                enqueued += 1
        await session.commit()

    return {"enqueued": enqueued}


@celery_app.task(name="email.dispatch_payment_reminders", queue="notifications")  # type: ignore[untyped-decorator]
def dispatch_payment_reminders() -> dict[str, Any]:
    """Beat-scheduled daily reminder sweep. Skipped when email is disabled so a
    mail-off deployment doesn't accumulate undeliverable reminder rows."""
    if not settings.MAIL_ENABLED:
        return {"skipped": "mail disabled"}
    return asyncio.run(_dispatch_payment_reminders())
