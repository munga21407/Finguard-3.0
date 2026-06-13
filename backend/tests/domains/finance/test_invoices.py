import uuid
from decimal import Decimal

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_create_invoice(client: AsyncClient, seed_customer: str) -> None:
    payload = {
        "customer_id": seed_customer,
        "invoice_number": f"INV-{uuid.uuid4().hex[:8].upper()}",
        "subtotal": "1000.00",
        "tax": "160.00",
        "currency": "KES",
    }
    res = await client.post("/api/v1/finance/invoices", json=payload)
    assert res.status_code == 201
    data = res.json()
    assert data["invoice_number"] == payload["invoice_number"]
    assert Decimal(data["total"]) == Decimal("1160.00")


@pytest.mark.asyncio
async def test_duplicate_invoice_number(client: AsyncClient, seed_customer: str) -> None:
    payload = {
        "customer_id": seed_customer,
        "invoice_number": f"INV-{uuid.uuid4().hex[:8].upper()}",
        "subtotal": "500.00",
    }
    first = await client.post("/api/v1/finance/invoices", json=payload)
    assert first.status_code == 201
    res = await client.post("/api/v1/finance/invoices", json=payload)
    assert res.status_code == 409
