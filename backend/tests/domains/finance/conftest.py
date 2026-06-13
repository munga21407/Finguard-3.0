"""
Finance-domain test fixtures.

Provides:
  * an authenticated-user override so router-level ``get_current_user``
    dependencies resolve without a real JWT, and
  * ``seed_customer`` — inserts a Customer row (invoices/expenses FK to it).

Table creation is handled by the resilient session-scoped ``create_tables``
fixture in the parent conftest, which skips pgvector tables when the extension
is unavailable.
"""
from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest_asyncio

from src.domains.crm.models import Customer
from src.domains.identity.dependencies import get_current_user
from src.domains.identity.models import User, UserRole
from src.main import app
from tests.conftest import TestingSessionLocal


@pytest_asyncio.fixture(autouse=True)
async def _override_auth() -> AsyncIterator[None]:
    """Resolve get_current_user to a fixed active OWNER for HTTP-level tests."""
    fake_user = User(
        id=uuid.uuid4(),
        email="finance-tester@finguard.local",
        hashed_password="x",
        full_name="Finance Tester",
        role=UserRole.OWNER,
        is_active=True,
        is_verified=True,
    )

    async def _override_get_current_user() -> User:
        return fake_user

    app.dependency_overrides[get_current_user] = _override_get_current_user
    yield
    app.dependency_overrides.pop(get_current_user, None)


@pytest_asyncio.fixture
async def seed_customer() -> str:
    """Insert a Customer and return its id (invoices/expenses require a real FK)."""
    customer = Customer(
        name="Acme Ltd",
        email=f"acme-{uuid.uuid4().hex[:8]}@example.com",
    )
    async with TestingSessionLocal() as session:
        session.add(customer)
        await session.commit()
        return str(customer.id)
