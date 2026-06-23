"""Event-sourcing fold for the invoice lifecycle.

The append-only ``invoice_events`` log is the source of truth for an invoice's
monetary state.  ``fold_invoice_events`` is a **pure** function that replays the
event sequence into a derived :class:`InvoiceState`; the service layer applies
that state to the materialized ``invoices`` row (a synchronous projection) so the
fast read path and the ``CHECK (balance_due = total - amount_paid)`` constraint
are preserved while the *derivation* stays fully auditable.

Keeping the fold pure (no ORM/session) means it can reconstruct state from any
event source — live rows, a test list, or a snapshot + tail (see
``fold_from_snapshot``) — and is trivially unit-testable.

Snapshotting: :class:`InvoiceState` is fully serialisable (``to_snapshot`` /
``from_snapshot``) and carries enough running accumulator state
(``last_payment_at``, ``sequence``) that resuming the fold from a snapshot plus
the events after it yields a state *identical* to a full replay.  The projection
writes a snapshot every ``SNAPSHOT_INTERVAL`` events so the log can grow without
the replay cost growing with it.

Async projection (moving the materialized-row update off the request path onto
the outbox/RabbitMQ consumer) is a deliberate follow-up — today the projection is
synchronous; the snapshot seam below is what keeps that synchronous path cheap.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from src.domains.finance.models import InvoiceEvent, InvoiceEventType, InvoiceStatus

# Statuses owned by the projection.  The fold only ever derives these; manual /
# non-payment statuses (DRAFT, SENT, OVERDUE) are left untouched so an operator's
# status transitions are not clobbered by replaying the event log.  CANCELLED is
# included because an INVOICE_CANCELLED event is authoritative over the status.
_PROJECTION_DERIVED_STATUSES = frozenset(
    {InvoiceStatus.PAID, InvoiceStatus.PARTIALLY_PAID, InvoiceStatus.CANCELLED}
)

# How many events accumulate before the projection writes a fresh snapshot.  A
# snapshot is a pure cache, so the exact value only trades snapshot write volume
# against replay-tail length; 50 keeps the synchronous projection's tail short.
SNAPSHOT_INTERVAL = 50


@dataclass(frozen=True)
class InvoiceState:
    """Invoice monetary state derived purely from the event log.

    ``total`` is the issued amount; ``credited`` is the sum of credit notes;
    ``balance_due = total - credited - amount_paid``.  ``last_payment_at`` and
    ``sequence`` are running accumulator fields retained so a snapshot can resume
    the fold exactly (the finalized ``paid_at`` is None unless fully settled, so
    it cannot by itself carry the last payment timestamp across a snapshot).
    """

    total: Decimal
    amount_paid: Decimal
    credited: Decimal
    balance_due: Decimal
    # None means "the fold does not own the status" — i.e. no payment/credit/cancel
    # has been applied yet, so the caller should keep the invoice's existing status.
    payment_status: InvoiceStatus | None
    paid_at: datetime | None
    issued: bool
    cancelled: bool
    event_count: int
    last_payment_at: datetime | None
    sequence: int

    def to_snapshot(self) -> dict[str, Any]:
        """Serialise to a JSON-safe dict for the ``invoice_snapshots`` cache."""
        return {
            "total": str(self.total),
            "amount_paid": str(self.amount_paid),
            "credited": str(self.credited),
            "balance_due": str(self.balance_due),
            "payment_status": self.payment_status.value if self.payment_status else None,
            "paid_at": self.paid_at.isoformat() if self.paid_at else None,
            "issued": self.issued,
            "cancelled": self.cancelled,
            "event_count": self.event_count,
            "last_payment_at": self.last_payment_at.isoformat() if self.last_payment_at else None,
            "sequence": self.sequence,
        }

    @classmethod
    def from_snapshot(cls, data: dict[str, Any]) -> InvoiceState:
        """Inverse of :meth:`to_snapshot`."""
        return cls(
            total=Decimal(data["total"]),
            amount_paid=Decimal(data["amount_paid"]),
            credited=Decimal(data["credited"]),
            balance_due=Decimal(data["balance_due"]),
            payment_status=(
                InvoiceStatus(data["payment_status"]) if data["payment_status"] else None
            ),
            paid_at=_parse_dt(data["paid_at"]),
            issued=data["issued"],
            cancelled=data["cancelled"],
            event_count=data["event_count"],
            last_payment_at=_parse_dt(data["last_payment_at"]),
            sequence=data["sequence"],
        )


def _parse_dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


@dataclass
class _Acc:
    """Mutable running accumulator threaded through the fold."""

    total: Decimal = Decimal("0")
    amount_paid: Decimal = Decimal("0")
    credited: Decimal = Decimal("0")
    last_payment_at: datetime | None = None
    issued: bool = False
    cancelled: bool = False
    count: int = 0
    sequence: int = 0


def _acc_from_state(state: InvoiceState) -> _Acc:
    return _Acc(
        total=state.total,
        amount_paid=state.amount_paid,
        credited=state.credited,
        last_payment_at=state.last_payment_at,
        issued=state.issued,
        cancelled=state.cancelled,
        count=state.event_count,
        sequence=state.sequence,
    )


def _apply(acc: _Acc, event: InvoiceEvent) -> None:
    """Fold a single event into the accumulator (in place)."""
    acc.count += 1
    acc.sequence = max(acc.sequence, event.sequence)
    # A cancelled invoice is terminal: later monetary events (which the service
    # guards against emitting) leave the money state untouched.
    if acc.cancelled:
        return
    if event.event_type == InvoiceEventType.INVOICE_ISSUED:
        acc.total = Decimal(event.amount)
        acc.issued = True
    elif event.event_type == InvoiceEventType.PAYMENT_APPLIED:
        acc.amount_paid += Decimal(event.amount)
        acc.last_payment_at = event.occurred_at
    elif event.event_type == InvoiceEventType.CREDIT_NOTE_APPLIED:
        acc.credited += Decimal(event.amount)
    elif event.event_type == InvoiceEventType.INVOICE_CANCELLED:
        acc.cancelled = True


def _finalize(acc: _Acc) -> InvoiceState:
    balance_due = acc.total - acc.credited - acc.amount_paid

    if acc.cancelled:
        payment_status: InvoiceStatus | None = InvoiceStatus.CANCELLED
        paid_at: datetime | None = None
    elif acc.amount_paid <= Decimal("0"):
        # No cash applied → the fold does not own the status (a fully-credited but
        # unpaid invoice keeps its operator status).
        payment_status = None
        paid_at = None
    elif balance_due <= Decimal("0"):
        payment_status = InvoiceStatus.PAID
        paid_at = acc.last_payment_at  # last payment settles it
    else:
        payment_status = InvoiceStatus.PARTIALLY_PAID
        paid_at = None  # only a fully-settled invoice carries a paid_at

    return InvoiceState(
        total=acc.total,
        amount_paid=acc.amount_paid,
        credited=acc.credited,
        balance_due=balance_due,
        payment_status=payment_status,
        paid_at=paid_at,
        issued=acc.issued,
        cancelled=acc.cancelled,
        event_count=acc.count,
        last_payment_at=acc.last_payment_at,
        sequence=acc.sequence,
    )


def _fold(base: InvoiceState | None, events: Sequence[InvoiceEvent]) -> InvoiceState:
    acc = _acc_from_state(base) if base is not None else _Acc()
    for event in sorted(events, key=lambda e: e.sequence):
        _apply(acc, event)
    return _finalize(acc)


def fold_invoice_events(events: Sequence[InvoiceEvent]) -> InvoiceState:
    """Replay an invoice's full event sequence into its derived monetary state.

    Events are folded in ``sequence`` order regardless of input ordering, so a
    caller may pass rows in any order.  Returns a zero/``issued=False`` state for
    an empty log (e.g. an invoice that predates event sourcing).
    """
    return _fold(None, events)


def fold_from_snapshot(
    snapshot: InvoiceState, tail_events: Sequence[InvoiceEvent]
) -> InvoiceState:
    """Resume the fold from a snapshot plus the events recorded after it.

    ``tail_events`` must be exactly the events with ``sequence > snapshot.sequence``.
    The result is identical to ``fold_invoice_events`` over the whole log — the
    snapshot is purely an optimisation that skips replaying the already-folded
    prefix.
    """
    return _fold(snapshot, tail_events)


def is_projection_derived_status(status: InvoiceStatus) -> bool:
    """True if ``status`` is one the projection is authoritative over."""
    return status in _PROJECTION_DERIVED_STATUSES
