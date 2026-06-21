import enum
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.domains.finance.types import VaultType
from src.infrastructure.database.postgres import Base


class TransactionType(enum.StrEnum):
    DEBIT = "debit"
    CREDIT = "credit"


class InvoiceEventType(enum.StrEnum):
    """Domain events appended to the append-only ``invoice_events`` log.

    The invoice's monetary state (``amount_paid`` / ``balance_due`` / ``status``)
    is *derived* by folding these events — the materialized ``invoices`` row is a
    synchronous projection of the fold (see ``finance/events.py``).  Extend with
    ``CREDIT_NOTE_APPLIED`` / ``INVOICE_CANCELLED`` when those flows are wired.
    """

    INVOICE_ISSUED = "invoice_issued"
    PAYMENT_APPLIED = "payment_applied"


class InvoiceStatus(enum.StrEnum):
    DRAFT = "draft"
    SENT = "sent"
    PAID = "paid"
    PARTIALLY_PAID = "partially_paid"
    OVERDUE = "overdue"
    CANCELLED = "cancelled"


class PaymentMethod(enum.StrEnum):
    BANK_TRANSFER = "bank_transfer"
    CARD = "card"
    MPESA = "mpesa"
    CASH = "cash"


class LedgerEntry(Base):
    __tablename__ = "ledger_entries"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    customer_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    transaction_type: Mapped[TransactionType] = mapped_column(Enum(TransactionType), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="KES", nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    reference: Mapped[str | None] = mapped_column(String(255), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Invoice(Base):
    __tablename__ = "invoices"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id"), nullable=False, index=True
    )
    invoice_number: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    status: Mapped[InvoiceStatus] = mapped_column(
        Enum(InvoiceStatus), default=InvoiceStatus.DRAFT, nullable=False
    )
    subtotal: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    tax: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    total: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    amount_paid: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), default=Decimal("0"), nullable=False
    )
    balance_due: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="KES", nullable=False)
    due_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    payments: Mapped[list["Payment"]] = relationship("Payment", back_populates="invoice")


class InvoiceEvent(Base):
    """Append-only event log for the invoice lifecycle (event-sourcing).

    Every monetary mutation to an invoice (issuance, payment application) is
    recorded here as an immutable row.  ``sequence`` is a per-invoice monotonic
    version starting at 1; the ``(invoice_id, sequence)`` uniqueness guarantees a
    gap-free, replayable history (writers serialise on the invoice row's
    ``FOR UPDATE`` lock).  ``amount`` carries the event's signed monetary
    contribution — the invoice total for ``invoice_issued``, the paid amount for
    ``payment_applied``.  Rows are never updated or deleted.
    """

    __tablename__ = "invoice_events"
    __table_args__ = (
        UniqueConstraint("invoice_id", "sequence", name="uq_invoice_events_invoice_seq"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    invoice_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("invoices.id"), nullable=False, index=True
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[InvoiceEventType] = mapped_column(
        Enum(InvoiceEventType, native_enum=False, length=50), nullable=False
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0"))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Budget(Base):
    __tablename__ = "budgets"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    spent: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    currency: Mapped[str] = mapped_column(String(3), default="KES", nullable=False)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class MpesaTransaction(Base):
    """Raw M-Pesa Daraja STK Push callback payloads."""

    __tablename__ = "mpesa_transactions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    trans_id: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    phone: Mapped[str] = mapped_column(String(20), nullable=False)
    bill_ref: Mapped[str | None] = mapped_column(String(100))
    vault: Mapped[VaultType] = mapped_column(
        Enum(VaultType), nullable=False, default=VaultType.MPESA
    )
    # Full raw Daraja callback envelope, retained for audit and dispute
    # resolution.  Nullable for rows written before this column existed.
    raw_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    is_reconciled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    expenses: Mapped[list["Expense"]] = relationship("Expense", back_populates="mpesa_transaction")


class Expense(Base):
    """An expense record linked to a vault, optionally to a customer and/or invoice."""

    __tablename__ = "expenses"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    expense_ref: Mapped[str | None] = mapped_column(String(50), index=True)
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id"), index=True
    )
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    vault: Mapped[VaultType] = mapped_column(Enum(VaultType), nullable=False)
    mpesa_trans_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("mpesa_transactions.id"), index=True
    )
    invoice_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("invoices.id"), index=True
    )
    # ── Receipt-scan provenance (nullable; populated by POST /finance/receipts) ──
    # merchant_name + kra_pin preserve the OCR audit trail; kra_pin feeds Agent F
    # (tax compliance).  receipt_date is the printed transaction date, which may
    # differ from created_at (when the row was inserted).
    merchant_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    kra_pin: Mapped[str | None] = mapped_column(String(20), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    receipt_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    mpesa_transaction: Mapped["MpesaTransaction | None"] = relationship(
        "MpesaTransaction", back_populates="expenses"
    )


class Payment(Base):
    """A payment recorded against an invoice — the immutable money-movement row.

    Created by every settlement path: manual cash (``record_cash_payment``) and
    automated reconciliation of M-Pesa transactions / bank statement lines
    (Agent C → ``apply_reconciled_payment``).  ``vault`` is the settlement rail;
    ``mpesa_trans_id`` / ``bank_line_id`` link back to the raw settlement record
    that produced it (NULL for manual cash).  ``recorded_by`` is NULL for
    agent-applied payments (no human actor), mirroring ``InvoiceEvent.recorded_by``.
    """

    __tablename__ = "payments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    invoice_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("invoices.id"), nullable=False, index=True
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    vault: Mapped[VaultType] = mapped_column(Enum(VaultType), nullable=False)
    reference_note: Mapped[str | None] = mapped_column(Text)
    payment_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    # Provenance: which raw settlement record reconciliation matched to this
    # invoice (NULL for manual cash payments).
    mpesa_trans_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("mpesa_transactions.id"), index=True
    )
    bank_line_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bank_statement_lines.id"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    invoice: Mapped["Invoice"] = relationship("Invoice", back_populates="payments")


class BankStatementLine(Base):
    """
    Raw bank statement line used by Agent C (Reconciler) for ledger matching.

    Two-pass reconciliation checks this table for exact (amount + date ±2 days +
    reference substring) and fuzzy (Gemini) matches against `ledger_entries`.
    """

    __tablename__ = "bank_statement_lines"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    reference_text: Mapped[str | None] = mapped_column(Text)
    is_reconciled: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class VaultTransfer(Base):
    """An internal treasury movement of the business's own money between vaults.

    Distinct from a Payment (customer inflow) or Expense (outflow): a transfer is
    net-zero to total cash — it only shifts money from ``from_vault`` to
    ``to_vault``.  An optional ``fee`` (M-Pesa/bank charge) is a real cost, booked
    as a separate ``Expense`` (vault = source) and linked via ``fee_expense_id``;
    the per-vault balance fold therefore subtracts the fee through the expense, not
    here.  Balances are derived (Σ payments + transfers_in − expenses − transfers_out),
    so this table is never the source of a stored balance.
    """

    __tablename__ = "vault_transfers"
    __table_args__ = (
        CheckConstraint("from_vault <> to_vault", name="ck_vault_transfers_distinct_vaults"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    from_vault: Mapped[VaultType] = mapped_column(Enum(VaultType), nullable=False)
    to_vault: Mapped[VaultType] = mapped_column(Enum(VaultType), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    fee: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"), nullable=False)
    reference_note: Mapped[str | None] = mapped_column(Text)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    # The Expense row that captured the transfer fee (NULL when fee == 0).
    fee_expense_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("expenses.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class OutboxEvent(Base):
    """Transactional outbox table for guaranteed message delivery."""

    __tablename__ = "outbox_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    exchange: Mapped[str] = mapped_column(String(100), nullable=False)
    routing_key: Mapped[str] = mapped_column(String(255), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    published: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
