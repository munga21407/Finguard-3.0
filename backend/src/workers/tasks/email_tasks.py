"""Email outbox flush worker.

The enqueue-side (``NotificationService``) writes ``email_outbox`` rows inside the
triggering business transaction; this Celery-beat task drains them. It mirrors the
message-outbox projector: lock a batch (``FOR UPDATE SKIP LOCKED`` so concurrent
workers take disjoint sets), then render + send each row **one at a time in its own
try/except** so one bad recipient can't roll back the batch. A transient failure
bumps ``attempts`` and leaves the row for the next pass; once ``attempts`` reaches
``EMAIL_MAX_RETRIES`` the row is *moved* to ``email_dead_letters`` so a poison
message never blocks the pipeline.
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.core.logging import logger
from src.infrastructure.database.postgres import AsyncSessionLocal
from src.infrastructure.email.smtp import send_email
from src.workers.tasks.celery_app import celery_app

# Bounded so SMTP round-trips don't hold row locks for long (email sends are
# slower than broker publishes — smaller than the message projector's 100).
_BATCH_SIZE = 25


async def _flush_email_outbox(
    session_factory: Callable[[], AsyncSession] = AsyncSessionLocal,
) -> dict[str, Any]:
    """Drain one batch. ``session_factory`` is injectable so tests can point the
    flush at the test database instead of the app engine."""
    sent = 0
    failed = 0
    dead_lettered = 0

    async with session_factory() as session:
        # Lazy import avoids circular deps at module load time.
        from src.domains.notifications.models import (  # noqa: PLC0415
            EmailDeadLetter,
            EmailOutbox,
            EmailStatus,
        )

        async with session.begin():
            now = datetime.now(UTC)
            result = await session.execute(
                select(EmailOutbox)
                .where(
                    EmailOutbox.status.in_((EmailStatus.PENDING, EmailStatus.FAILED)),
                    or_(
                        EmailOutbox.scheduled_for.is_(None),
                        EmailOutbox.scheduled_for <= now,
                    ),
                )
                .order_by(EmailOutbox.created_at.asc())
                .limit(_BATCH_SIZE)
                .with_for_update(skip_locked=True)
            )
            rows = result.scalars().all()

            for row in rows:
                try:
                    await send_email(
                        to_email=row.to_email,
                        to_name=row.to_name,
                        subject=row.subject,
                        template=row.template,
                        context=row.context,
                    )
                except Exception as exc:  # noqa: BLE001 — isolate one email's failure
                    row.attempts += 1
                    row.last_error = repr(exc)[:1000]
                    if row.attempts >= settings.EMAIL_MAX_RETRIES:
                        session.add(
                            EmailDeadLetter(
                                original_email_id=row.id,
                                to_email=row.to_email,
                                to_name=row.to_name,
                                subject=row.subject,
                                template=row.template,
                                context=row.context,
                                attempts=row.attempts,
                                last_error=row.last_error,
                                idempotency_key=row.idempotency_key,
                                original_created_at=row.created_at,
                            )
                        )
                        await session.delete(row)
                        dead_lettered += 1
                        logger.error(
                            "email dead-lettered after exhausting retries",
                            email_id=str(row.id),
                            template=row.template,
                            attempts=row.attempts,
                            last_error=row.last_error,
                        )
                    else:
                        row.status = EmailStatus.FAILED
                        failed += 1
                        logger.warning(
                            "email send failed; will retry",
                            email_id=str(row.id),
                            template=row.template,
                            attempts=row.attempts,
                            max_retries=settings.EMAIL_MAX_RETRIES,
                        )
                    continue

                row.status = EmailStatus.SENT
                row.sent_at = datetime.now(UTC)
                sent += 1

    return {"sent": sent, "failed": failed, "dead_lettered": dead_lettered}


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
