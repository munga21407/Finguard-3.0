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

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import NotFoundError
from src.core.logging import logger
from src.domains.notifications.models import (
    SUPPRESSIBLE_CATEGORIES,
    EmailCategory,
    EmailDeadLetter,
    EmailOptOut,
    EmailOutbox,
    EmailStatus,
)


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
        category: EmailCategory = EmailCategory.ACCOUNT,
        to_name: str | None = None,
        scheduled_for: datetime | None = None,
    ) -> bool:
        """Queue one email for delivery. Returns True if a new row was enqueued.

        A missing recipient is a skip, not an error: some triggers (e.g. an
        agent-applied payment whose customer has no email on file) legitimately
        have no one to notify, and that must never fail the business action.

        Suppressible categories (approval / reminder) are dropped when the
        recipient has opted out; transactional categories (account / receipt /
        invoice) always send.
        """
        if not to_email:
            logger.info(
                "email skipped — no recipient", template=template, key=idempotency_key
            )
            return False

        if category in SUPPRESSIBLE_CATEGORIES and await self._is_opted_out(
            to_email, category
        ):
            logger.info(
                "email suppressed by preference",
                template=template,
                category=category.value,
                key=idempotency_key,
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

    # ── Admin: outbox inspection + replay/resend ───────────────────────────────

    async def list_outbox(
        self,
        *,
        status: EmailStatus | None = None,
        template: str | None = None,
        to_email: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[EmailOutbox], int]:
        """Filtered, paginated outbox rows + total count (most recent first)."""
        conds = []
        if status is not None:
            conds.append(EmailOutbox.status == status)
        if template:
            conds.append(EmailOutbox.template == template)
        if to_email:
            conds.append(EmailOutbox.to_email == to_email.lower())
        total = await self._session.scalar(
            select(func.count()).select_from(EmailOutbox).where(*conds)
        ) or 0
        rows = await self._session.execute(
            select(EmailOutbox)
            .where(*conds)
            .order_by(EmailOutbox.created_at.desc())
            .limit(min(limit, 200))
            .offset(offset)
        )
        return list(rows.scalars().all()), total

    async def list_dead_letters(
        self, *, limit: int = 50, offset: int = 0
    ) -> tuple[list[EmailDeadLetter], int]:
        total = await self._session.scalar(
            select(func.count()).select_from(EmailDeadLetter)
        ) or 0
        rows = await self._session.execute(
            select(EmailDeadLetter)
            .order_by(EmailDeadLetter.dead_lettered_at.desc())
            .limit(min(limit, 200))
            .offset(offset)
        )
        return list(rows.scalars().all()), total

    async def kpis(self) -> dict[str, int]:
        """Outbox counts by status + dead-letter total, for the ops dashboard."""
        result = await self._session.execute(
            select(EmailOutbox.status, func.count()).group_by(EmailOutbox.status)
        )
        by_status: dict[EmailStatus, int] = {row[0]: int(row[1]) for row in result.all()}
        dead = await self._session.scalar(
            select(func.count()).select_from(EmailDeadLetter)
        ) or 0
        return {
            "pending": int(by_status.get(EmailStatus.PENDING, 0)),
            "sent": int(by_status.get(EmailStatus.SENT, 0)),
            "failed": int(by_status.get(EmailStatus.FAILED, 0)),
            "dead_lettered": int(dead),
        }

    async def replay_dead_letter(self, dead_letter_id: uuid.UUID) -> EmailOutbox:
        """Re-queue a dead-lettered email: insert a fresh outbox row (attempts 0)
        and remove the dead-letter. A new idempotency key means it always sends."""
        dl = await self._session.get(EmailDeadLetter, dead_letter_id)
        if not dl:
            raise NotFoundError("Dead-lettered email not found")
        row = EmailOutbox(
            to_email=dl.to_email,
            to_name=dl.to_name,
            subject=dl.subject,
            template=dl.template,
            context=dl.context,
            status=EmailStatus.PENDING,
            idempotency_key=f"{dl.idempotency_key}:replay:{uuid.uuid4()}",
        )
        self._session.add(row)
        await self._session.delete(dl)
        await self._session.commit()
        await self._session.refresh(row)
        return row

    async def resend(self, outbox_id: uuid.UUID) -> EmailOutbox:
        """Re-queue a delivered (or any) outbox row as a fresh pending send."""
        src = await self._session.get(EmailOutbox, outbox_id)
        if not src:
            raise NotFoundError("Email not found")
        row = EmailOutbox(
            to_email=src.to_email,
            to_name=src.to_name,
            subject=src.subject,
            template=src.template,
            context=src.context,
            status=EmailStatus.PENDING,
            idempotency_key=f"{src.idempotency_key}:resend:{uuid.uuid4()}",
        )
        self._session.add(row)
        await self._session.commit()
        await self._session.refresh(row)
        return row

    # ── Preferences (opt-outs) ─────────────────────────────────────────────────

    async def _is_opted_out(self, email: str, category: EmailCategory) -> bool:
        found = await self._session.scalar(
            select(EmailOptOut.id)
            .where(
                EmailOptOut.email == email.lower(),
                EmailOptOut.category == category,
            )
            .limit(1)
        )
        return found is not None

    async def list_opt_outs(self, email: str) -> set[EmailCategory]:
        """The categories *email* has opted out of (suppressible ones only)."""
        rows = await self._session.execute(
            select(EmailOptOut.category).where(EmailOptOut.email == email.lower())
        )
        return set(rows.scalars().all())

    async def set_opt_out(
        self, email: str, category: EmailCategory, *, opted_out: bool
    ) -> None:
        """Opt *email* out of / back into a suppressible *category*.

        Transactional categories can't be opted out of (they're mandatory), so a
        request to suppress one is ignored. Commits its own change.
        """
        if category not in SUPPRESSIBLE_CATEGORIES:
            return
        email = email.lower()
        if opted_out:
            await self._session.execute(
                pg_insert(EmailOptOut)
                .values(id=uuid.uuid4(), email=email, category=category)
                .on_conflict_do_nothing(index_elements=["email", "category"])
            )
        else:
            await self._session.execute(
                delete(EmailOptOut).where(
                    EmailOptOut.email == email,
                    EmailOptOut.category == category,
                )
            )
        await self._session.commit()
