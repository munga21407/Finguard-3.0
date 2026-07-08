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
