"""
Regression tests for finance event delivery via the transactional outbox.

Before Sprint 1, ``create_expense`` and ``process_mpesa_callback`` published to
RabbitMQ *after* commit, so a broker outage silently dropped the event while the
database row persisted.  Both now enqueue an OutboxEvent inside the same
transaction; the projector delivers it with at-least-once semantics.

Also covers the stricter M-Pesa callback validation that refuses to persist a
transaction with a blank receipt / zero amount.
"""
from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import UnprocessableError
from src.domains.finance.models import Expense, MpesaTransaction, OutboxEvent
from src.domains.finance.schemas import ExpenseCreate, MpesaCallbackPayload
from src.domains.finance.service import FinanceService
from src.domains.finance.types import VaultType


async def _outbox_events(session: AsyncSession, routing_key: str) -> list[OutboxEvent]:
    result = await session.execute(
        select(OutboxEvent).where(OutboxEvent.routing_key == routing_key)
    )
    return list(result.scalars().all())


def _mpesa_body(
    *,
    receipt: str,
    amount: int | float = 100,
    phone: str = "254700000000",
    result_code: int = 0,
    checkout: str = "ws_CO_123",
    with_metadata: bool = True,
) -> dict:
    stk: dict = {
        "MerchantRequestID": "m-req-1",
        "CheckoutRequestID": checkout,
        "ResultCode": result_code,
        "ResultDesc": "The service request is processed successfully."
        if result_code == 0
        else "Request cancelled by user",
    }
    if with_metadata:
        stk["CallbackMetadata"] = {
            "Item": [
                {"Name": "Amount", "Value": amount},
                {"Name": "MpesaReceiptNumber", "Value": receipt},
                {"Name": "PhoneNumber", "Value": phone},
            ]
        }
    return {"stkCallback": stk}


# ── Expenses ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_expense_enqueues_outbox_event(db_session: AsyncSession) -> None:
    svc = FinanceService(db_session)
    expense = await svc.create_expense(
        ExpenseCreate(category="utilities", amount=Decimal("250.00"), vault=VaultType.CASH)
    )

    events = await _outbox_events(db_session, "expenses.created")
    mine = [e for e in events if e.payload["payload"]["expense_id"] == str(expense.id)]
    assert len(mine) == 1, "expense must enqueue exactly one outbox event"
    assert mine[0].published is False, "outbox event must start unpublished"
    assert mine[0].exchange == "finguard.events"

    # The expense row itself persisted.
    assert await db_session.get(Expense, expense.id) is not None


# ── M-Pesa: happy path ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_mpesa_success_persists_with_raw_payload_and_outbox(
    db_session: AsyncSession,
) -> None:
    receipt = f"RCPT{uuid.uuid4().hex[:8].upper()}"
    body = _mpesa_body(receipt=receipt, amount=500)

    svc = FinanceService(db_session)
    resp = await svc.process_mpesa_callback(MpesaCallbackPayload(Body=body))

    assert resp is not None
    assert resp.trans_id == receipt
    assert resp.amount == Decimal("500")

    txn = await db_session.get(MpesaTransaction, resp.id)
    assert txn is not None
    assert txn.raw_payload == body, "raw Daraja envelope must be retained for audit"

    events = await _outbox_events(db_session, "mpesa.reconciled")
    mine = [e for e in events if e.payload["payload"]["trans_id"] == receipt]
    assert len(mine) == 1
    assert mine[0].published is False


# ── M-Pesa: rejection paths ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_mpesa_failed_callback_is_ignored(db_session: AsyncSession) -> None:
    body = _mpesa_body(receipt="SHOULD_NOT_PERSIST", result_code=1032, with_metadata=False)
    svc = FinanceService(db_session)
    resp = await svc.process_mpesa_callback(MpesaCallbackPayload(Body=body))
    assert resp is None
    # Nothing should have been persisted for a cancelled payment.
    result = await db_session.execute(
        select(MpesaTransaction).where(MpesaTransaction.trans_id == "SHOULD_NOT_PERSIST")
    )
    assert result.scalars().first() is None


@pytest.mark.asyncio
async def test_mpesa_success_without_metadata_is_rejected(db_session: AsyncSession) -> None:
    # ResultCode 0 but no CallbackMetadata — must NOT persist a blank transaction.
    body = _mpesa_body(receipt="X", result_code=0, with_metadata=False)
    svc = FinanceService(db_session)
    with pytest.raises(UnprocessableError):
        await svc.process_mpesa_callback(MpesaCallbackPayload(Body=body))


@pytest.mark.asyncio
async def test_mpesa_malformed_envelope_is_rejected(db_session: AsyncSession) -> None:
    svc = FinanceService(db_session)
    with pytest.raises(UnprocessableError):
        await svc.process_mpesa_callback(MpesaCallbackPayload(Body={"not_stk": {}}))


@pytest.mark.asyncio
async def test_mpesa_duplicate_callback_is_idempotent(db_session: AsyncSession) -> None:
    receipt = f"DUP{uuid.uuid4().hex[:8].upper()}"
    body = _mpesa_body(receipt=receipt, amount=750)
    svc = FinanceService(db_session)

    first = await svc.process_mpesa_callback(MpesaCallbackPayload(Body=body))
    second = await svc.process_mpesa_callback(MpesaCallbackPayload(Body=body))

    assert first is not None and second is not None
    assert first.id == second.id, "duplicate receipt must return the same record"

    result = await db_session.execute(
        select(MpesaTransaction).where(MpesaTransaction.trans_id == receipt)
    )
    assert len(result.scalars().all()) == 1, "no duplicate transaction row"

    events = await _outbox_events(db_session, "mpesa.reconciled")
    mine = [e for e in events if e.payload["payload"]["trans_id"] == receipt]
    assert len(mine) == 1, "duplicate callback must not enqueue a second event"
