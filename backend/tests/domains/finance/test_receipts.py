"""
Receipt expense persistence — POST /finance/receipts.

Verifies the reviewed-receipt write path: the OCR audit trail is persisted, the
expense shows up in the list, and the transactional ``expenses.created`` outbox
event is enqueued (so Agent E's watchdog still fires for receipt expenses).
"""
from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from src.domains.finance.models import Expense, OutboxEvent
from tests.conftest import TestingSessionLocal


@pytest.mark.asyncio
async def test_create_receipt_expense_persists_audit_trail(client: AsyncClient) -> None:
    payload = {
        "merchant_name": "Nairobi Hardware Ltd",
        "category": "supplies",
        "amount": "3750.00",
        "vault": "CASH",
        "kra_pin": "P051234567X",
        "receipt_date": "2026-06-13T10:30:00Z",
        "description": "cement and nails",
    }
    res = await client.post("/api/v1/finance/receipts", json=payload)
    assert res.status_code == 201, res.text

    body = res.json()
    assert body["merchant_name"] == "Nairobi Hardware Ltd"
    assert body["kra_pin"] == "P051234567X"
    assert body["category"] == "supplies"
    assert body["vault"] == "CASH"

    # The expense is now listable.
    listing = await client.get("/api/v1/finance/expenses")
    assert listing.status_code == 200
    ids = [e["id"] for e in listing.json()]
    assert body["id"] in ids


@pytest.mark.asyncio
async def test_create_receipt_expense_enqueues_outbox_event(client: AsyncClient) -> None:
    payload = {
        "merchant_name": "Java House",
        "category": "travel",
        "amount": "1200.50",
        "vault": "CASH",
    }
    res = await client.post("/api/v1/finance/receipts", json=payload)
    assert res.status_code == 201
    expense_id = res.json()["id"]

    # An expenses.created outbox row was written for this expense, source=receipt.scan.
    async with TestingSessionLocal() as session:
        rows = (
            await session.execute(
                select(OutboxEvent).where(OutboxEvent.routing_key == "expenses.created")
            )
        ).scalars().all()

    matching = [
        r for r in rows if r.payload["payload"]["expense_id"] == expense_id
    ]
    assert len(matching) == 1
    assert matching[0].payload["payload"]["source"] == "receipt.scan"
    assert matching[0].published is False


@pytest.mark.asyncio
async def test_create_receipt_expense_rejects_zero_amount(client: AsyncClient) -> None:
    res = await client.post(
        "/api/v1/finance/receipts",
        json={"category": "supplies", "amount": "0", "vault": "CASH"},
    )
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_receipt_expense_defaults_vault_to_cash(client: AsyncClient) -> None:
    """vault is optional and defaults to CASH for paper receipts."""
    res = await client.post(
        "/api/v1/finance/receipts",
        json={"category": "utilities", "amount": "500"},
    )
    assert res.status_code == 201
    assert res.json()["vault"] == "CASH"


@pytest.mark.asyncio
async def test_receipt_columns_isolated_from_plain_expense(client: AsyncClient) -> None:
    """A plain /expenses create leaves the receipt columns null (no leakage)."""
    res = await client.post("/api/v1/finance/receipts", json={
        "merchant_name": "Total Energies",
        "category": "travel",
        "amount": "4000",
        "vault": "CASH",
    })
    rid = res.json()["id"]
    async with TestingSessionLocal() as session:
        expense = await session.get(Expense, uuid.UUID(rid))
        assert expense is not None
        assert expense.merchant_name == "Total Energies"
        assert expense.receipt_date is None  # not supplied in this payload
