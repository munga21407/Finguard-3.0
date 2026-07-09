"""HTTP surface for notification preferences + public unsubscribe."""
from __future__ import annotations

from collections.abc import Callable

import pytest
from httpx import AsyncClient

from src.core.security import create_unsubscribe_token
from src.domains.identity.models import User, UserRole


@pytest.mark.asyncio
async def test_preferences_default_all_subscribed(
    client: AsyncClient, auth_as: Callable[..., User]
) -> None:
    auth_as(UserRole.MANAGER)
    res = await client.get("/api/v1/notifications/preferences")
    assert res.status_code == 200
    prefs = res.json()["preferences"]
    cats = {p["category"] for p in prefs}
    assert cats == {"approval", "reminder"}          # only suppressible ones
    assert all(p["opted_out"] is False for p in prefs)


@pytest.mark.asyncio
async def test_update_preference_opts_out(
    client: AsyncClient, auth_as: Callable[..., User]
) -> None:
    auth_as(UserRole.MANAGER)
    res = await client.put(
        "/api/v1/notifications/preferences",
        json={"category": "reminder", "opted_out": True},
    )
    assert res.status_code == 200
    prefs = {p["category"]: p["opted_out"] for p in res.json()["preferences"]}
    assert prefs["reminder"] is True
    assert prefs["approval"] is False


@pytest.mark.asyncio
async def test_public_unsubscribe_link_opts_out(client: AsyncClient) -> None:
    token = create_unsubscribe_token("walkin@example.com", "reminder")
    res = await client.get(f"/api/v1/notifications/unsubscribe?token={token}")
    assert res.status_code == 200
    assert "unsubscribed" in res.text.lower()


@pytest.mark.asyncio
async def test_unsubscribe_rejects_bad_token(client: AsyncClient) -> None:
    res = await client.get("/api/v1/notifications/unsubscribe?token=not-a-real-token")
    assert res.status_code == 401
