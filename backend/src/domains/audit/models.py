import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Enum, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.database.postgres import Base


class AuditActorType(enum.StrEnum):
    """Who initiated the recorded activity."""

    USER = "user"        # an authenticated human (actor_id → users.id)
    AGENT = "agent"      # an intelligence agent (actor_label → agent name)
    SYSTEM = "system"    # an unattended job / the platform itself


class AuditOutcome(enum.StrEnum):
    SUCCESS = "success"
    FAILURE = "failure"
    DENIED = "denied"    # blocked by authz / a guard before taking effect


class AuditAction(enum.StrEnum):
    """Canonical action verbs (``<resource>.<verb>``).

    Stored in the ``action`` *string* column rather than a native PG enum: the
    set of audited activities grows continuously, and a String column lets new
    verbs land without an enum-altering migration. This enum is the registry of
    well-known values so call sites stay consistent and greppable.
    """

    AUTH_LOGIN = "auth.login"
    AUTH_LOGIN_FAILED = "auth.login_failed"
    AUTH_LOGOUT = "auth.logout"
    ALERT_CREATED = "alert.created"
    ALERT_RESOLVED = "alert.resolved"
    # Finance — invoices (receivables)
    INVOICE_CREATED = "invoice.created"
    INVOICE_UPDATED = "invoice.updated"
    INVOICE_PAID = "invoice.paid"
    INVOICE_CANCELLED = "invoice.cancelled"
    CREDIT_NOTE_APPLIED = "credit_note.applied"
    # Finance — accounts payable (expenses + approval queue)
    EXPENSE_CREATED = "expense.created"
    PAYMENT_RECORDED = "payment.recorded"      # manual cash payment against an invoice
    BUDGET_CREATED = "budget.created"
    PAYABLE_SUBMITTED = "payable.submitted"
    PAYABLE_APPROVED = "payable.approved"
    PAYABLE_REJECTED = "payable.rejected"
    PAYABLE_SCHEDULED = "payable.scheduled"
    # CRM
    CRM_CUSTOMER_CREATED = "crm.customer.created"
    CRM_CUSTOMER_UPDATED = "crm.customer.updated"
    # Intelligence — agent orchestration runs
    AGENT_ACTION_RUN = "agent.action_run"


class AuditLog(Base):
    """An append-only record of a meaningful system activity (who/what/when).

    Written only via :class:`~src.domains.audit.service.AuditService` at explicit
    service/router call sites — never updated or deleted (immutability is the
    point of an audit trail). Read by the audit/activity-log API.
    """

    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    actor_type: Mapped[AuditActorType] = mapped_column(
        Enum(AuditActorType, name="audit_actor_type"), nullable=False
    )
    # Null for non-user actors (agent/system). FK kept nullable + ON DELETE
    # untouched so removing a user never erases their audit history.
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True
    )
    # Human-readable actor label: the user's email, the agent name, or a service
    # identifier — denormalised so the trail stays legible even if the user row
    # is later changed or removed.
    actor_label: Mapped[str | None] = mapped_column(String(255), nullable=True)

    action: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    resource_type: Mapped[str] = mapped_column(String(50), nullable=False)
    resource_id: Mapped[str | None] = mapped_column(String(100), nullable=True)

    outcome: Mapped[AuditOutcome] = mapped_column(
        Enum(AuditOutcome, name="audit_outcome"),
        default=AuditOutcome.SUCCESS,
        nullable=False,
    )

    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)  # IPv6-sized
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    metadata_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
