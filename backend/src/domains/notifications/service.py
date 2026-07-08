"""Enqueue-side of the transactional email pipeline.

Callers enqueue an email in the **same transaction** as the business write that
triggers it (e.g. inside ``register`` or ``apply_reconciled_payment``); a
Celery-beat flush task (``workers.tasks.email_tasks``) later renders and sends it.
This service deliberately does not commit — the caller owns the transaction
boundary so the email row lands atomically with the business change (or not at
all).

Dedupe is enforced at the database via ``ON CONFLICT (idempotency_key) DO
NOTHING``: re-triggering the same logical event (same ``idempotency_key``) is a
silent no-op, so an email is enqueued at most once.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.logging import logger
from src.domains.notifications.models import EmailOutbox, EmailStatus


class NotificationService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def enqueue_email(
        self,
        *,
        to_email: str | None,
        subject: str,
        template: str,
        context: dict[str, Any],
        idempotency_key: str,
        to_name: str | None = None,
        scheduled_for: datetime | None = None,
    ) -> bool:
        """Queue one email for delivery. Returns True if a new row was enqueued.

        A missing recipient is a skip, not an error: some triggers (e.g. an
        agent-applied payment whose customer has no email on file) legitimately
        have no one to notify, and that must never fail the business action.
        """
        if not to_email:
            logger.info(
                "email skipped — no recipient", template=template, key=idempotency_key
            )
            return False

        stmt = (
            pg_insert(EmailOutbox)
            .values(
                id=uuid.uuid4(),
                to_email=to_email,
                to_name=to_name,
                subject=subject,
                template=template,
                context=context,
                status=EmailStatus.PENDING,
                scheduled_for=scheduled_for,
                idempotency_key=idempotency_key,
            )
            # Re-triggering the same logical event is a no-op (enqueue at most once).
            .on_conflict_do_nothing(index_elements=["idempotency_key"])
            # RETURNING yields the id only when a row was actually inserted;
            # on conflict it yields nothing — a type-safe "did we enqueue?" check.
            .returning(EmailOutbox.id)
        )
        result = await self._session.execute(stmt)
        enqueued = result.scalar_one_or_none() is not None
        if enqueued:
            logger.info("email enqueued", template=template, key=idempotency_key)
        return enqueued
