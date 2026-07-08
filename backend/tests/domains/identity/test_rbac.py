"""
HTTP-level RBAC enforcement across finance, CRM, and intelligence routes.

Denials short-circuit at the permission dependency (403) before any handler /
DB / Gemini work runs.  Allowed cases use side-effect-light endpoints so the
test confirms the gate passes without invoking the orchestrator.
"""
from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient

from src.domains.identity.models import User, UserRole


def _budget_body() -> dict:
    now = datetime.now(UTC)
    return {
        "name": "Q3 Ops",
        "category": "operations",
        "amount": "10000.00",
        "currency": "KES",
        "period_start": now.isoformat(),
        "period_end": (now + timedelta(days=90)).isoformat(),
    }


def _customer_body() -> dict:
    return {"name": "Acme Ltd", "email": f"acme-{uuid.uuid4().hex[:8]}@example.com"}


# ── Denials ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_viewer_denied_finance_write(
    client: AsyncClient, auth_as: Callable[..., User]
) -> None:
    auth_as(UserRole.VIEWER)
    res = await client.post("/api/v1/finance/budgets", json=_budget_body())
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_viewer_denied_crm_write(
    client: AsyncClient, auth_as: Callable[..., User]
) -> None:
    auth_as(UserRole.VIEWER)
    res = await client.post("/api/v1/crm/customers", json=_customer_body())
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_viewer_denied_intelligence_action(
    client: AsyncClient, auth_as: Callable[..., User]
) -> None:
    auth_as(UserRole.VIEWER)
    res = await client.post(
        "/api/v1/intelligence/ai-actions",
        json={"intent": "pay everyone"},
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_accountant_denied_user_management(
    client: AsyncClient, auth_as: Callable[..., User]
) -> None:
    auth_as(UserRole.ACCOUNTANT)
    res = await client.get("/api/v1/identity/users")
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_accountant_denied_payable_approval(
    client: AsyncClient, auth_as: Callable[..., User]
) -> None:
    """Signing off an AP payable needs finance:approve (manager+), not finance:write.

    The denial short-circuits at the permission dependency (403) before the handler,
    so no payable need exist — an Accountant can submit but cannot approve.
    """
    auth_as(UserRole.ACCOUNTANT)
    res = await client.post(f"/api/v1/finance/payables/{uuid.uuid4()}/approve")
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_accountant_denied_agent_proposal_approval(
    client: AsyncClient, auth_as: Callable[..., User]
) -> None:
    """Approving an agent-proposed stock adjustment needs inventory:adjust (manager+).

    The denial short-circuits at the permission dependency (403) before the handler,
    so no proposal need exist — an Accountant simply lacks the authority to release
    an agent action.
    """
    auth_as(UserRole.ACCOUNTANT)
    res = await client.post(
        f"/api/v1/intelligence/proposals/{uuid.uuid4()}/approve"
    )
    assert res.status_code == 403


# ── Grants ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_viewer_allowed_finance_read(
    client: AsyncClient, auth_as: Callable[..., User]
) -> None:
    auth_as(UserRole.VIEWER)
    res = await client.get("/api/v1/finance/budgets")
    assert res.status_code == 200


@pytest.mark.asyncio
async def test_accountant_allowed_finance_write(
    client: AsyncClient, auth_as: Callable[..., User]
) -> None:
    auth_as(UserRole.ACCOUNTANT)
    res = await client.post("/api/v1/finance/budgets", json=_budget_body())
    assert res.status_code == 201


@pytest.mark.asyncio
async def test_accountant_allowed_crm_write(
    client: AsyncClient, auth_as: Callable[..., User]
) -> None:
    auth_as(UserRole.ACCOUNTANT)
    res = await client.post("/api/v1/crm/customers", json=_customer_body())
    assert res.status_code == 201


@pytest.mark.asyncio
async def test_owner_allowed_user_management(
    client: AsyncClient, auth_as: Callable[..., User]
) -> None:
    auth_as(UserRole.OWNER)
    res = await client.get("/api/v1/identity/users")
    assert res.status_code == 200
