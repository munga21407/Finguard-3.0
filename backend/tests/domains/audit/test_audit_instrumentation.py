"""End-to-end audit instrumentation for state-mutating endpoints.

Proves the cross-cutting contract added across the finance / CRM / intelligence
routers: a successful state change writes exactly one audit row attributed to the
acting user.  Uses a *committed* user so the ``audit_logs.actor_id → users.id``
foreign key is satisfied (the write path the real endpoints exercise).
"""
from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.domains.audit.models import AuditAction, AuditActorType
from src.domains.audit.service import AuditService
from src.domains.identity.dependencies import get_current_user
from src.domains.identity.models import User, UserRole
from src.main import app
from tests.conftest import TestingSessionLocal


@pytest_asyncio.fixture
async def committed_owner() -> AsyncIterator[User]:
    """A persisted OWNER whose id can back an audit row's actor_id FK."""
    user = User(
        id=uuid.uuid4(),
        email=f"owner-{uuid.uuid4().hex[:8]}@finguard.local",
        hashed_password="x",
        full_name="Audit Owner",
        role=UserRole.OWNER,
        is_active=True,
        is_verified=True,
    )
    async with TestingSessionLocal() as session:
        session.add(user)
        await session.commit()

    async def _override() -> User:
        return user

    app.dependency_overrides[get_current_user] = _override
    yield user
    app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.asyncio
async def test_create_customer_writes_audit_row(
    client: AsyncClient, committed_owner: User, db_session: AsyncSession
) -> None:
    res = await client.post(
        "/api/v1/crm/customers",
        json={"name": "Audit Co", "email": f"c-{uuid.uuid4().hex[:8]}@example.com"},
    )
    assert res.status_code == 201
    customer_id = res.json()["id"]

    logs, total = await AuditService(db_session).query(
        action=AuditAction.CRM_CUSTOMER_CREATED.value
    )
    assert total == 1
    entry = logs[0]
    assert entry.actor_id == committed_owner.id
    assert entry.actor_type == AuditActorType.USER
    assert entry.resource_type == "customer"
    assert entry.resource_id == customer_id


@pytest.mark.asyncio
async def test_create_invoice_writes_audit_row(
    client: AsyncClient, committed_owner: User, db_session: AsyncSession
) -> None:
    customer = await client.post(
        "/api/v1/crm/customers",
        json={"name": "Inv Co", "email": f"i-{uuid.uuid4().hex[:8]}@example.com"},
    )
    assert customer.status_code == 201

    res = await client.post(
        "/api/v1/finance/invoices",
        json={
            "customer_id": customer.json()["id"],
            "invoice_number": f"INV-{uuid.uuid4().hex[:8].upper()}",
            "subtotal": "1000.00",
            "tax": "0",
        },
    )
    assert res.status_code == 201
    invoice_id = res.json()["id"]

    logs, total = await AuditService(db_session).query(
        action=AuditAction.INVOICE_CREATED.value
    )
    assert total == 1
    assert logs[0].actor_id == committed_owner.id
    assert logs[0].resource_id == invoice_id


@pytest.mark.asyncio
async def test_create_budget_writes_audit_row(
    client: AsyncClient, committed_owner: User, db_session: AsyncSession
) -> None:
    res = await client.post(
        "/api/v1/finance/budgets",
        json={
            "name": "Q3 Marketing",
            "category": "marketing",
            "amount": "50000.00",
            "period_start": "2026-07-01T00:00:00Z",
            "period_end": "2026-09-30T00:00:00Z",
        },
    )
    assert res.status_code == 201
    budget_id = res.json()["id"]

    logs, total = await AuditService(db_session).query(
        action=AuditAction.BUDGET_CREATED.value
    )
    assert total == 1
    assert logs[0].actor_id == committed_owner.id
    assert logs[0].resource_type == "budget"
    assert logs[0].resource_id == budget_id


@pytest.mark.asyncio
async def test_record_cash_payment_writes_audit_row(
    client: AsyncClient, committed_owner: User, db_session: AsyncSession
) -> None:
    customer = await client.post(
        "/api/v1/crm/customers",
        json={"name": "Pay Co", "email": f"p-{uuid.uuid4().hex[:8]}@example.com"},
    )
    assert customer.status_code == 201
    invoice = await client.post(
        "/api/v1/finance/invoices",
        json={
            "customer_id": customer.json()["id"],
            "invoice_number": f"INV-{uuid.uuid4().hex[:8].upper()}",
            "subtotal": "1000.00",
            "tax": "0",
        },
    )
    assert invoice.status_code == 201

    res = await client.post(
        "/api/v1/finance/payments/cash",
        json={
            "invoice_id": invoice.json()["id"],
            "amount": "250.00",
            "payment_date": "2026-06-23T00:00:00Z",
        },
    )
    assert res.status_code == 201
    payment_id = res.json()["id"]

    logs, total = await AuditService(db_session).query(
        action=AuditAction.PAYMENT_RECORDED.value
    )
    assert total == 1
    assert logs[0].actor_id == committed_owner.id
    assert logs[0].resource_type == "payment"
    assert logs[0].resource_id == payment_id


@pytest.mark.asyncio
async def test_audit_failure_does_not_break_the_action(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """An un-persisted actor breaks the audit FK, but the action still succeeds.

    This is the ``record_safe`` isolation contract: instrumentation must never
    turn a successful mutation into a 500.  Here ``get_current_user`` resolves to
    a user that is NOT in the DB, so the audit insert violates the actor FK — the
    customer is still created and the request returns 201.
    """
    ghost = User(
        id=uuid.uuid4(),
        email=f"ghost-{uuid.uuid4().hex[:8]}@finguard.local",
        hashed_password="x",
        full_name="Ghost",
        role=UserRole.OWNER,
        is_active=True,
        is_verified=True,
    )

    async def _override() -> User:
        return ghost

    app.dependency_overrides[get_current_user] = _override
    try:
        res = await client.post(
            "/api/v1/crm/customers",
            json={"name": "Ghost Co", "email": f"g-{uuid.uuid4().hex[:8]}@example.com"},
        )
        assert res.status_code == 201
        # No audit row was written (the FK rejected it), but the action survived.
        _, total = await AuditService(db_session).query(
            resource_id=res.json()["id"]
        )
        assert total == 0
    finally:
        app.dependency_overrides.pop(get_current_user, None)
