"""
CRM-domain test fixtures.

CRM routes now require crm:read / crm:write permissions.  These tests focus on
CRM behaviour rather than authorization, so an authenticated OWNER (who holds
every permission) is injected by overriding ``get_current_user``.  RBAC denial
is covered separately in the identity RBAC matrix tests.
"""
from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest_asyncio

from src.domains.identity.dependencies import get_current_user
from src.domains.identity.models import User, UserRole
from src.main import app


@pytest_asyncio.fixture(autouse=True)
async def _override_auth() -> AsyncIterator[None]:
    owner = User(
        id=uuid.uuid4(),
        email="crm-tester@finguard.local",
        hashed_password="x",
        full_name="CRM Tester",
        role=UserRole.OWNER,
        is_active=True,
        is_verified=True,
    )

    async def _override_get_current_user() -> User:
        return owner

    app.dependency_overrides[get_current_user] = _override_get_current_user
    yield
    app.dependency_overrides.pop(get_current_user, None)
