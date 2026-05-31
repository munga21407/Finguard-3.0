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
