"""``POST /conversation/{session_id}/resume`` records its outcome via
``agent_checkpoint_resume_total{outcome}`` — added alongside the Grafana
panels for the checkpointing staging bake (see
docs/CHECKPOINTING_STAGING_BAKE.md). Mirrors test_conversation_idor.py's
fixture style (seed Redis directly, hit the real endpoint via the test
client) rather than mocking the router.
"""
from __future__ import annotations

import json
import uuid
from collections.abc import Callable

import pytest
from httpx import AsyncClient
from prometheus_client import Counter

from src.core.metrics import CHECKPOINT_RESUME_OUTCOME
from src.domains.identity.models import User, UserRole
from src.infrastructure.cache.redis import get_redis


def _sample(counter: Counter, **labels: str) -> float:
    return counter.labels(**labels)._value.get()


@pytest.mark.asyncio
async def test_resume_dispatched_increments_dispatched_outcome(
    client: AsyncClient, auth_as: Callable[..., User]
) -> None:
    session_id = str(uuid.uuid4())
    owner = auth_as(UserRole.MANAGER)
    redis = get_redis()
    await redis.setex(f"task_owner:{session_id}", 3600, str(owner.id))
    await redis.setex(
        f"task_status:{session_id}", 3600,
        json.dumps({"status": "failed", "resumable": True}),
    )

    before = _sample(CHECKPOINT_RESUME_OUTCOME, outcome="dispatched")
    res = await client.post(f"/api/v1/intelligence/conversation/{session_id}/resume")

    assert res.status_code == 200
    assert res.json()["status"] == "pending"
    assert _sample(CHECKPOINT_RESUME_OUTCOME, outcome="dispatched") == before + 1


@pytest.mark.asyncio
async def test_resume_not_resumable_increments_that_outcome(
    client: AsyncClient, auth_as: Callable[..., User]
) -> None:
    session_id = str(uuid.uuid4())
    owner = auth_as(UserRole.MANAGER)
    redis = get_redis()
    await redis.setex(f"task_owner:{session_id}", 3600, str(owner.id))
    await redis.setex(
        f"task_status:{session_id}", 3600,
        json.dumps({"status": "failed", "resumable": False}),
    )

    before = _sample(CHECKPOINT_RESUME_OUTCOME, outcome="not_resumable")
    res = await client.post(f"/api/v1/intelligence/conversation/{session_id}/resume")

    assert res.status_code == 409
    assert _sample(CHECKPOINT_RESUME_OUTCOME, outcome="not_resumable") == before + 1


@pytest.mark.asyncio
async def test_resume_unknown_session_increments_not_found_outcome(
    client: AsyncClient, auth_as: Callable[..., User]
) -> None:
    auth_as(UserRole.MANAGER)
    session_id = str(uuid.uuid4())  # never seeded in Redis

    before = _sample(CHECKPOINT_RESUME_OUTCOME, outcome="not_found")
    res = await client.post(f"/api/v1/intelligence/conversation/{session_id}/resume")

    assert res.status_code == 404
    assert _sample(CHECKPOINT_RESUME_OUTCOME, outcome="not_found") == before + 1
