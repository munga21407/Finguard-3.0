"""
Conversation status endpoint must not leak another user's session (IDOR).
"""
from __future__ import annotations

import json
import uuid
from collections.abc import Callable

import pytest
from httpx import AsyncClient

from src.domains.identity.models import User, UserRole
from src.infrastructure.cache.redis import get_redis


@pytest.mark.asyncio
async def test_status_only_visible_to_owning_user(
    client: AsyncClient, auth_as: Callable[..., User]
) -> None:
    session_id = str(uuid.uuid4())

    owner = auth_as(UserRole.MANAGER)
    redis = get_redis()
    await redis.setex(f"task_owner:{session_id}", 3600, str(owner.id))
    await redis.setex(
        f"task_status:{session_id}", 3600, json.dumps({"status": "completed"})
    )

    # The owner can read their session status.
    res_owner = await client.get(
        f"/api/v1/intelligence/conversation/{session_id}/status"
    )
    assert res_owner.status_code == 200
    assert res_owner.json()["status"] == "completed"

    # A different authenticated user is denied — 404 (no existence leak).
    auth_as(UserRole.MANAGER)  # a fresh user with a different id
    res_other = await client.get(
        f"/api/v1/intelligence/conversation/{session_id}/status"
    )
    assert res_other.status_code == 404
