"""Event-sourcing fold for the invoice lifecycle.

The append-only ``invoice_events`` log is the source of truth for an invoice's
monetary state.  ``fold_invoice_events`` is a **pure** function that replays the
event sequence into a derived :class:`InvoiceState`; the service layer applies
that state to the materialized ``invoices`` row (a synchronous projection) so the
fast read path and the ``CHECK (balance_due = total - amount_paid)`` constraint
are preserved while the *derivation* stays fully auditable.

Keeping the fold pure (no ORM/session) means it can reconstruct state from any
event source — live rows, a test list, or a future snapshot + tail — and is
trivially unit-testable.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from src.domains.finance.models import InvoiceEvent, InvoiceEventType, InvoiceStatus

# Statuses owned by the payment lifecycle.  The fold only ever derives these;
# manual/non-payment statuses (DRAFT, SENT, OVERDUE) are left untouched so an
# operator's status transitions are not clobbered by replaying payment events.
_PAYMENT_DERIVED_STATUSES = frozenset(
    {InvoiceStatus.PAID, InvoiceStatus.PARTIALLY_PAID}
)


@dataclass(frozen=True)
class InvoiceState:
    """Invoice monetary state derived purely from the event log."""

    total: Decimal
    amount_paid: Decimal
    balance_due: Decimal
    # None means "the fold does not own the status" — i.e. no payment has been
    # applied yet, so the caller should keep the invoice's existing status.
    payment_status: InvoiceStatus | None
    paid_at: datetime | None
    issued: bool
    event_count: int


def fold_invoice_events(events: Sequence[InvoiceEvent]) -> InvoiceState:
    """Replay an invoice's event sequence into its derived monetary state.

    Events are folded in ``sequence`` order regardless of input ordering, so a
    caller may pass rows in any order.  Returns a zero/``issued=False`` state for
    an empty log (e.g. an invoice that predates event sourcing).
    """
    total = Decimal("0")
    amount_paid = Decimal("0")
    paid_at: datetime | None = None
    issued = False

    ordered = sorted(events, key=lambda e: e.sequence)
    for event in ordered:
        if event.event_type == InvoiceEventType.INVOICE_ISSUED:
            total = Decimal(event.amount)
            issued = True
        elif event.event_type == InvoiceEventType.PAYMENT_APPLIED:
            amount_paid += Decimal(event.amount)
            paid_at = event.occurred_at  # last payment timestamp; overwritten on settle

    balance_due = total - amount_paid

    if amount_paid <= Decimal("0"):
        payment_status: InvoiceStatus | None = None
        paid_at = None
    elif balance_due <= Decimal("0"):
        payment_status = InvoiceStatus.PAID
    else:
        payment_status = InvoiceStatus.PARTIALLY_PAID
        paid_at = None  # only a fully-settled invoice carries a paid_at

    return InvoiceState(
        total=total,
        amount_paid=amount_paid,
        balance_due=balance_due,
        payment_status=payment_status,
        paid_at=paid_at,
        issued=issued,
        event_count=len(ordered),
    )


def is_payment_derived_status(status: InvoiceStatus) -> bool:
    """True if ``status`` is one the payment fold is authoritative over."""
    return status in _PAYMENT_DERIVED_STATUSES
