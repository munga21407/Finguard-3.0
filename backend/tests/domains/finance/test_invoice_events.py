"""
Tests for invoice event sourcing.

Covers the pure fold (`fold_invoice_events`) and the service-level integration:
issuance and payments append immutable events, the materialized invoice row is a
faithful projection of folding them, and `reconstruct_invoice` confirms the read
model never drifts from the append-only source of truth.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domains.finance.events import (
    SNAPSHOT_INTERVAL,
    InvoiceState,
    fold_from_snapshot,
    fold_invoice_events,
)
from src.domains.finance.models import (
    Invoice,
    InvoiceEvent,
    InvoiceEventType,
    InvoiceStatus,
    Payment,
)
from src.domains.finance.schemas import InvoiceCreate, PaymentCreate
from src.domains.finance.service import FinanceService
from src.domains.finance.types import VaultType
from src.domains.identity.models import User, UserRole


def _fake_user() -> User:
    return User(
        id=uuid.uuid4(),
        email=f"payer-{uuid.uuid4().hex[:8]}@finguard.local",
        hashed_password="x",
        full_name="Payer",
        role=UserRole.ACCOUNTANT,
        is_active=True,
        is_verified=True,
    )


async def _make_invoice(svc: FinanceService, customer_id: str, *, subtotal: str) -> Invoice:
    return await svc.create_invoice(
        InvoiceCreate(
            customer_id=uuid.UUID(customer_id),
            invoice_number=f"INV-{uuid.uuid4().hex[:10].upper()}",
            subtotal=Decimal(subtotal),
            tax=Decimal("0"),
        )
    )


def _event(seq: int, etype: InvoiceEventType, amount: str) -> InvoiceEvent:
    return InvoiceEvent(
        invoice_id=uuid.uuid4(),
        sequence=seq,
        event_type=etype,
        amount=Decimal(amount),
        payload={},
        occurred_at=datetime.now(UTC),
    )


# ── Pure fold unit tests (no DB) ──────────────────────────────────────────────

def test_fold_empty_log_is_unissued_zero_state() -> None:
    state = fold_invoice_events([])
    assert state.issued is False
    assert state.total == Decimal("0")
    assert state.amount_paid == Decimal("0")
    assert state.balance_due == Decimal("0")
    assert state.payment_status is None
    assert state.paid_at is None


def test_fold_issued_only_has_no_payment_status() -> None:
    state = fold_invoice_events([_event(1, InvoiceEventType.INVOICE_ISSUED, "1000")])
    assert state.issued is True
    assert state.total == Decimal("1000")
    assert state.balance_due == Decimal("1000")
    # No payment yet → fold does not own the status (leaves DRAFT/SENT alone).
    assert state.payment_status is None


def test_fold_partial_payment_is_partially_paid() -> None:
    state = fold_invoice_events(
        [
            _event(1, InvoiceEventType.INVOICE_ISSUED, "1000"),
            _event(2, InvoiceEventType.PAYMENT_APPLIED, "400"),
        ]
    )
    assert state.amount_paid == Decimal("400")
    assert state.balance_due == Decimal("600")
    assert state.payment_status == InvoiceStatus.PARTIALLY_PAID
    assert state.paid_at is None


def test_fold_full_payment_is_paid_with_timestamp() -> None:
    state = fold_invoice_events(
        [
            _event(1, InvoiceEventType.INVOICE_ISSUED, "1000"),
            _event(2, InvoiceEventType.PAYMENT_APPLIED, "600"),
            _event(3, InvoiceEventType.PAYMENT_APPLIED, "400"),
        ]
    )
    assert state.amount_paid == Decimal("1000")
    assert state.balance_due == Decimal("0")
    assert state.payment_status == InvoiceStatus.PAID
    assert state.paid_at is not None


def test_fold_is_order_independent() -> None:
    issued = _event(1, InvoiceEventType.INVOICE_ISSUED, "500")
    pay = _event(2, InvoiceEventType.PAYMENT_APPLIED, "500")
    forward = fold_invoice_events([issued, pay])
    reversed_ = fold_invoice_events([pay, issued])
    assert forward.balance_due == reversed_.balance_due == Decimal("0")
    assert reversed_.payment_status == InvoiceStatus.PAID


# ── Credit notes + cancellation ───────────────────────────────────────────────

def test_fold_credit_note_reduces_balance() -> None:
    state = fold_invoice_events(
        [
            _event(1, InvoiceEventType.INVOICE_ISSUED, "1000"),
            _event(2, InvoiceEventType.PAYMENT_APPLIED, "400"),
            _event(3, InvoiceEventType.CREDIT_NOTE_APPLIED, "100"),
        ]
    )
    assert state.credited == Decimal("100")
    # balance_due = total - credited - amount_paid
    assert state.balance_due == Decimal("500")
    assert state.payment_status == InvoiceStatus.PARTIALLY_PAID


def test_fold_credit_note_can_settle_remaining_balance() -> None:
    state = fold_invoice_events(
        [
            _event(1, InvoiceEventType.INVOICE_ISSUED, "1000"),
            _event(2, InvoiceEventType.PAYMENT_APPLIED, "400"),
            _event(3, InvoiceEventType.CREDIT_NOTE_APPLIED, "600"),
        ]
    )
    assert state.balance_due == Decimal("0")
    # A payment exists and the balance is cleared → PAID, carrying the payment time.
    assert state.payment_status == InvoiceStatus.PAID
    assert state.paid_at is not None


def test_fold_cancellation_is_terminal() -> None:
    state = fold_invoice_events(
        [
            _event(1, InvoiceEventType.INVOICE_ISSUED, "1000"),
            _event(2, InvoiceEventType.INVOICE_CANCELLED, "0"),
        ]
    )
    assert state.cancelled is True
    assert state.payment_status == InvoiceStatus.CANCELLED
    assert state.paid_at is None


# ── Snapshotting ──────────────────────────────────────────────────────────────

def _seq_event(
    invoice_id: uuid.UUID, seq: int, etype: InvoiceEventType, amount: str, *, day: int
) -> InvoiceEvent:
    """Event for one invoice with a deterministic, sequence-ordered timestamp."""
    return InvoiceEvent(
        invoice_id=invoice_id,
        sequence=seq,
        event_type=etype,
        amount=Decimal(amount),
        payload={},
        occurred_at=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=day),
    )


def test_snapshot_round_trips() -> None:
    state = fold_invoice_events(
        [
            _event(1, InvoiceEventType.INVOICE_ISSUED, "1000"),
            _event(2, InvoiceEventType.PAYMENT_APPLIED, "1000"),
        ]
    )
    assert InvoiceState.from_snapshot(state.to_snapshot()) == state


def test_fold_from_snapshot_equals_full_replay() -> None:
    """Resuming from a snapshot + tail must be identical to replaying the whole log.

    Mixes payments and credit notes across a log longer than SNAPSHOT_INTERVAL so
    the snapshot boundary is genuinely exercised.
    """
    inv = uuid.uuid4()
    events = [_seq_event(inv, 1, InvoiceEventType.INVOICE_ISSUED, "100000", day=0)]
    for seq in range(2, 2 * SNAPSHOT_INTERVAL + 12):
        if seq % 3 == 0:
            events.append(
                _seq_event(inv, seq, InvoiceEventType.CREDIT_NOTE_APPLIED, "50", day=seq)
            )
        else:
            events.append(
                _seq_event(inv, seq, InvoiceEventType.PAYMENT_APPLIED, "100", day=seq)
            )

    full = fold_invoice_events(events)
    base = fold_invoice_events(events[:SNAPSHOT_INTERVAL])
    tail = [e for e in events if e.sequence > base.sequence]
    resumed = fold_from_snapshot(InvoiceState.from_snapshot(base.to_snapshot()), tail)
    assert resumed == full


# ── Service integration tests (DB) ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_invoice_appends_issued_event(
    db_session: AsyncSession, seed_customer: str
) -> None:
    svc = FinanceService(db_session)
    invoice = await _make_invoice(svc, seed_customer, subtotal="1000")

    events = await svc.get_invoice_events(invoice.id)
    assert len(events) == 1
    assert events[0].sequence == 1
    assert events[0].event_type == InvoiceEventType.INVOICE_ISSUED
    assert events[0].amount == Decimal("1000")


@pytest.mark.asyncio
async def test_payment_appends_event_and_projection_matches(
    db_session: AsyncSession, seed_customer: str
) -> None:
    svc = FinanceService(db_session)
    user = _fake_user()
    invoice = await _make_invoice(svc, seed_customer, subtotal="1000")
    now = datetime.now(UTC)

    await svc.record_cash_payment(
        PaymentCreate(invoice_id=invoice.id, amount=Decimal("400"), payment_date=now), user
    )

    events = await svc.get_invoice_events(invoice.id)
    assert [e.event_type for e in events] == [
        InvoiceEventType.INVOICE_ISSUED,
        InvoiceEventType.PAYMENT_APPLIED,
    ]
    assert [e.sequence for e in events] == [1, 2]

    # The materialized row equals the fold of its events.
    inv, state, _ = await svc.reconstruct_invoice(invoice.id)
    assert inv.amount_paid == state.amount_paid == Decimal("400")
    assert inv.balance_due == state.balance_due == Decimal("600")
    assert inv.status == InvoiceStatus.PARTIALLY_PAID == state.payment_status


@pytest.mark.asyncio
async def test_full_settlement_event_chain_reconstructs(
    db_session: AsyncSession, seed_customer: str
) -> None:
    svc = FinanceService(db_session)
    user = _fake_user()
    invoice = await _make_invoice(svc, seed_customer, subtotal="1000")
    now = datetime.now(UTC)

    await svc.record_cash_payment(
        PaymentCreate(invoice_id=invoice.id, amount=Decimal("600"), payment_date=now), user
    )
    await svc.record_cash_payment(
        PaymentCreate(
            invoice_id=invoice.id, amount=Decimal("400"), payment_date=now + timedelta(minutes=1)
        ),
        user,
    )

    inv, state, events = await svc.reconstruct_invoice(invoice.id)
    assert len(events) == 3  # issued + 2 payments
    assert inv.balance_due == state.balance_due == Decimal("0")
    assert inv.status == InvoiceStatus.PAID
    assert inv.paid_at is not None


@pytest.mark.asyncio
async def test_mark_invoice_paid_appends_settlement_event(
    db_session: AsyncSession, seed_customer: str
) -> None:
    svc = FinanceService(db_session)
    invoice = await _make_invoice(svc, seed_customer, subtotal="750")

    await svc.mark_invoice_paid(invoice.id)

    inv, state, events = await svc.reconstruct_invoice(invoice.id)
    # issued + one settlement payment_applied for the full balance
    assert [e.event_type for e in events] == [
        InvoiceEventType.INVOICE_ISSUED,
        InvoiceEventType.PAYMENT_APPLIED,
    ]
    assert events[1].payload.get("reason") == "manual_settlement"
    assert inv.status == InvoiceStatus.PAID
    assert inv.balance_due == state.balance_due == Decimal("0")


@pytest.mark.asyncio
async def test_mark_invoice_paid_creates_backing_cash_payment(
    db_session: AsyncSession, seed_customer: str
) -> None:
    """Manual settlement is backed by a CASH Payment — no 'unlinked' amount_paid."""
    svc = FinanceService(db_session)
    invoice = await _make_invoice(svc, seed_customer, subtotal="750")

    await svc.mark_invoice_paid(invoice.id)

    payments = (
        await db_session.execute(select(Payment).where(Payment.invoice_id == invoice.id))
    ).scalars().all()
    assert len(payments) == 1
    assert payments[0].vault == VaultType.CASH
    assert payments[0].amount == Decimal("750")
    # amount_paid is fully backed by Payment rows — the unlinked gap is zero.
    inv = await db_session.get(Invoice, invoice.id)
    assert inv is not None
    assert sum(p.amount for p in payments) == inv.amount_paid


@pytest.mark.asyncio
async def test_mark_invoice_paid_records_chosen_rail(
    db_session: AsyncSession, seed_customer: str
) -> None:
    """The /pay caller can pick the settlement rail; the Payment lands on it."""
    svc = FinanceService(db_session)
    invoice = await _make_invoice(svc, seed_customer, subtotal="900")

    await svc.mark_invoice_paid(invoice.id, vault=VaultType.MPESA)

    payment = (
        await db_session.execute(select(Payment).where(Payment.invoice_id == invoice.id))
    ).scalar_one()
    assert payment.vault == VaultType.MPESA
    assert payment.amount == Decimal("900")


@pytest.mark.asyncio
async def test_reconstruction_reports_match(
    db_session: AsyncSession, seed_customer: str
) -> None:
    svc = FinanceService(db_session)
    user = _fake_user()
    invoice = await _make_invoice(svc, seed_customer, subtotal="200")
    await svc.record_cash_payment(
        PaymentCreate(
            invoice_id=invoice.id, amount=Decimal("200"), payment_date=datetime.now(UTC)
        ),
        user,
    )

    inv, state, _ = await svc.reconstruct_invoice(invoice.id)
    matches = (
        state.amount_paid == inv.amount_paid
        and state.balance_due == inv.balance_due
        and state.payment_status == inv.status
    )
    assert matches is True
