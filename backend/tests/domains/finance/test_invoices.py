import uuid
from decimal import Decimal

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_create_invoice(client: AsyncClient) -> None:
    customer_id = str(uuid.uuid4())
    payload = {
        "customer_id": customer_id,
        "invoice_number": "INV-0001",
        "subtotal": "1000.00",
        "tax": "160.00",
        "currency": "KES",
    }
    res = await client.post("/api/v1/finance/invoices", json=payload)
    assert res.status_code == 201
    data = res.json()
    assert data["invoice_number"] == "INV-0001"
    assert Decimal(data["total"]) == Decimal("1160.00")


@pytest.mark.asyncio
async def test_duplicate_invoice_number(client: AsyncClient) -> None:
    customer_id = str(uuid.uuid4())
    payload = {
        "customer_id": customer_id,
        "invoice_number": "INV-DUPE",
        "subtotal": "500.00",
    }
    await client.post("/api/v1/finance/invoices", json=payload)
    res = await client.post("/api/v1/finance/invoices", json=payload)
    assert res.status_code == 409
