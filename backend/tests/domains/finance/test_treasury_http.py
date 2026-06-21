"""HTTP-level tests for the treasury + reconciliation-flow endpoints.

Exercise the real FastAPI routes (auth, validation, serialization), not just the
service layer.  The finance conftest authenticates the client as an OWNER, who
holds every permission.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from src.domains.finance.models import Payment
from src.domains.finance.schemas import InvoiceCreate
from src.domains.finance.service import FinanceService
from src.domains.finance.types import VaultType
from tests.conftest import TestingSessionLocal


async def _fund_vault(customer_id: str, vault: VaultType, amount: str) -> None:
    """Give a vault a positive balance by settling a fresh invoice on it."""
    async with TestingSessionLocal() as session:
        svc = FinanceService(session)
        invoice = await svc.create_invoice(
            InvoiceCreate(
                customer_id=uuid.UUID(customer_id),
                invoice_number=f"INV-{uuid.uuid4().hex[:10].upper()}",
                subtotal=Decimal(amount),
                tax=Decimal("0"),
            )
        )
        await svc.mark_invoice_paid(invoice.id, vault=vault)


@pytest.mark.asyncio
async def test_vault_balances_endpoint(client: AsyncClient) -> None:
    res = await client.get("/api/v1/finance/vault-balances")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["currency"] == "KES"
    assert {b["vault"] for b in body["balances"]} == {"MPESA", "CASH", "BANK"}
    assert "total" in body


@pytest.mark.asyncio
async def test_vault_transfer_records_and_lists(client: AsyncClient, seed_customer: str) -> None:
    await _fund_vault(seed_customer, VaultType.MPESA, "60000")
    res = await client.post(
        "/api/v1/finance/vault-transfers",
        json={
            "from_vault": "MPESA",
            "to_vault": "BANK",
            "amount": 50000,
            "fee": 200,
            "occurred_at": datetime.now(UTC).isoformat(),
        },
    )
    assert res.status_code == 201, res.text
    created = res.json()
    assert created["from_vault"] == "MPESA"
    assert created["to_vault"] == "BANK"

    listed = await client.get("/api/v1/finance/vault-transfers")
    assert listed.status_code == 200
    assert any(t["id"] == created["id"] for t in listed.json())


@pytest.mark.asyncio
async def test_vault_transfer_same_vault_rejected(client: AsyncClient) -> None:
    res = await client.post(
        "/api/v1/finance/vault-transfers",
        json={
            "from_vault": "CASH",
            "to_vault": "CASH",
            "amount": 100,
            "occurred_at": datetime.now(UTC).isoformat(),
        },
    )
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_vault_transfer_overdraw_rejected(client: AsyncClient) -> None:
    # An astronomically large amount exceeds any vault's balance → overdraw guard.
    res = await client.post(
        "/api/v1/finance/vault-transfers",
        json={
            "from_vault": "BANK",
            "to_vault": "CASH",
            "amount": 999_999_999_999,
            "occurred_at": datetime.now(UTC).isoformat(),
        },
    )
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_reconciliation_flow_endpoint(client: AsyncClient) -> None:
    res = await client.get("/api/v1/finance/reconciliation-flow")
    assert res.status_code == 200, res.text
    body = res.json()
    assert "nodes" in body
    assert "links" in body
    assert body["currency"] == "KES"


@pytest.mark.asyncio
async def test_pay_endpoint_records_chosen_rail(client: AsyncClient, seed_customer: str) -> None:
    async with TestingSessionLocal() as session:
        invoice = await FinanceService(session).create_invoice(
            InvoiceCreate(
                customer_id=uuid.UUID(seed_customer),
                invoice_number=f"INV-{uuid.uuid4().hex[:10].upper()}",
                subtotal=Decimal("900"),
                tax=Decimal("0"),
            )
        )
        invoice_id = invoice.id

    res = await client.post(
        f"/api/v1/finance/invoices/{invoice_id}/pay", json={"vault": "BANK"}
    )
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "paid"

    async with TestingSessionLocal() as session:
        payment = (
            await session.execute(select(Payment).where(Payment.invoice_id == invoice_id))
        ).scalar_one()
        assert payment.vault == VaultType.BANK
        assert payment.amount == Decimal("900")
