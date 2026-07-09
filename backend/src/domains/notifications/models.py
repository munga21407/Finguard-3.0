"""Transactional email persistence — the delivery pipeline's source of truth.

Mirrors the message outbox (``finance.models.OutboxEvent`` / ``OutboxDeadLetter``):
a business action enqueues an :class:`EmailOutbox` row in its own transaction, and
a Celery-beat flush task renders + sends it via Gmail SMTP with at-least-once
semantics.  ``idempotency_key`` is unique so a re-triggered event can never
double-send; an email that exhausts ``EMAIL_MAX_RETRIES`` is *moved* to
:class:`EmailDeadLetter` so a poison message never blocks the pipeline.
"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    DateTime,
    Enum,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.database.postgres import Base


class EmailStatus(enum.StrEnum):
    PENDING = "pending"   # awaiting a flush pass
    SENT = "sent"         # accepted by the SMTP server (or dry-run logged)
    FAILED = "failed"     # transient failure; retried until dead-lettered


class EmailCategory(enum.StrEnum):
    """Category of a transactional email — governs opt-out eligibility.

    ACCOUNT / RECEIPT / INVOICE are transactional and cannot be suppressed (a
    recipient must always get their receipt or account mail). APPROVAL and
    REMINDER are suppressible via a per-recipient opt-out (see ``EmailOptOut`` and
    ``SUPPRESSIBLE_CATEGORIES``).
    """

    ACCOUNT = "account"     # welcome, account approved
    RECEIPT = "receipt"     # payment received
    INVOICE = "invoice"     # invoice issued
    APPROVAL = "approval"   # something needs your review
    REMINDER = "reminder"   # payment due / overdue


# Only these may be opted out of; the rest are mandatory transactional mail.
SUPPRESSIBLE_CATEGORIES: frozenset[EmailCategory] = frozenset(
    {EmailCategory.APPROVAL, EmailCategory.REMINDER}
)


class EmailOptOut(Base):
    """A recipient's opt-out of one suppressible email category.

    Keyed by (lowercased) email so it applies to both internal users and external
    customers uniformly. Presence of a row means opted out; absence means
    subscribed (default-in). Set via the authenticated preferences API or a signed
    unsubscribe link.
    """

    __tablename__ = "email_opt_outs"
    __table_args__ = (
        UniqueConstraint("email", "category", name="uq_email_opt_outs_email_category"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), nullable=False, index=True)
    category: Mapped[EmailCategory] = mapped_column(
        Enum(EmailCategory, native_enum=False, length=20), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class EmailOutbox(Base):
    __tablename__ = "email_outbox"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    to_email: Mapped[str] = mapped_column(String(320), nullable=False)
    to_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    # Template base name (renders ``{template}.html`` + ``{template}.txt``).
    template: Mapped[str] = mapped_column(String(100), nullable=False)
    context: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[EmailStatus] = mapped_column(
        Enum(EmailStatus, native_enum=False, length=20),
        default=EmailStatus.PENDING,
        nullable=False,
        index=True,
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Set to send in the future (e.g. reminders); NULL ⇒ send on the next flush.
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Unique dedupe key (e.g. "welcome:{user_id}"): re-triggering the same event is
    # a no-op, so an email is enqueued at most once.
    idempotency_key: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )


class EmailDeadLetter(Base):
    """Terminal resting place for emails that exhausted their retries.

    Moved here (copied, then deleted from ``email_outbox``) so the flush query
    stays small and a poison message never re-enters the send loop. Retained for
    operator inspection / manual replay; nothing reads it automatically.
    """

    __tablename__ = "email_dead_letters"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    original_email_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    to_email: Mapped[str] = mapped_column(String(320), nullable=False)
    to_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    template: Mapped[str] = mapped_column(String(100), nullable=False)
    context: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(120), nullable=False)
    original_created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    dead_lettered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
