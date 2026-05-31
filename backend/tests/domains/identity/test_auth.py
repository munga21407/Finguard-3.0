import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_register_and_login(client: AsyncClient) -> None:
    payload = {"email": "test@finguard.io", "password": "secure1234", "full_name": "Test User"}
    res = await client.post("/api/v1/identity/register", json=payload)
    assert res.status_code == 201
    data = res.json()
    assert data["email"] == payload["email"]

    res = await client.post(
        "/api/v1/identity/token",
        json={"email": payload["email"], "password": payload["password"]},
    )
    assert res.status_code == 200
    assert "access_token" in res.json()


@pytest.mark.asyncio
async def test_duplicate_registration(client: AsyncClient) -> None:
    payload = {"email": "dupe@finguard.io", "password": "secure1234", "full_name": "Dupe User"}
    await client.post("/api/v1/identity/register", json=payload)
    res = await client.post("/api/v1/identity/register", json=payload)
    assert res.status_code == 409


@pytest.mark.asyncio
async def test_invalid_credentials(client: AsyncClient) -> None:
    res = await client.post(
        "/api/v1/identity/token",
        json={"email": "nobody@finguard.io", "password": "wrong"},
    )
    assert res.status_code == 401
