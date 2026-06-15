import uuid

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_create_and_get_customer(client: AsyncClient) -> None:
    payload = {"name": "Acme Ltd", "email": "acme@example.com", "customer_type": "business"}
    res = await client.post("/api/v1/crm/customers", json=payload)
    assert res.status_code == 201
    customer_id = res.json()["id"]

    res = await client.get(f"/api/v1/crm/customers/{customer_id}")
    assert res.status_code == 200
    assert res.json()["name"] == "Acme Ltd"


@pytest.mark.asyncio
async def test_list_customers(client: AsyncClient) -> None:
    res = await client.get("/api/v1/crm/customers")
    assert res.status_code == 200
    assert isinstance(res.json(), list)


@pytest.mark.asyncio
async def test_duplicate_email_conflicts(client: AsyncClient) -> None:
    payload = {"name": "Dup Co", "email": "dup@example.com"}
    first = await client.post("/api/v1/crm/customers", json=payload)
    assert first.status_code == 201
    second = await client.post("/api/v1/crm/customers", json=payload)
    assert second.status_code == 409


@pytest.mark.asyncio
async def test_get_unknown_customer_returns_404(client: AsyncClient) -> None:
    res = await client.get(f"/api/v1/crm/customers/{uuid.uuid4()}")
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_update_customer_status_and_phone(client: AsyncClient) -> None:
    created = await client.post(
        "/api/v1/crm/customers",
        json={"name": "Mutable Ltd", "email": "mutable@example.com"},
    )
    customer_id = created.json()["id"]

    res = await client.patch(
        f"/api/v1/crm/customers/{customer_id}",
        json={"status": "active", "phone": "0712345678"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "active"
    assert body["phone"] == "0712345678"
