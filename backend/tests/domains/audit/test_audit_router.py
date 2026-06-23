"""HTTP-level tests for the audit / activity-log API.

Confirms the audit:read RBAC gate (managers+), that recorded entries are
queryable through the endpoint, and the end-to-end contract that resolving an
alert leaves exactly one ``alert.resolved`` audit row.
"""
from __future__ import annotations

import uuid
from collections.abc import Callable

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.domains.alerts.models import AlertSeverity, AlertStatus, AlertType
from src.domains.alerts.schemas import AlertCreate
from src.domains.alerts.service import AlertService
from src.domains.audit.models import AuditAction, AuditActorType
from src.domains.audit.service import AuditService
from src.domains.identity.models import User, UserRole

# ── RBAC ──────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_viewer_denied_audit_read(
    client: AsyncClient, auth_as: Callable[..., User]
) -> None:
    auth_as(UserRole.VIEWER)
    res = await client.get("/api/v1/audit")
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_accountant_denied_audit_read(
    client: AsyncClient, auth_as: Callable[..., User]
) -> None:
    auth_as(UserRole.ACCOUNTANT)
    res = await client.get("/api/v1/audit")
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_manager_allowed_audit_read(
    client: AsyncClient, auth_as: Callable[..., User]
) -> None:
    auth_as(UserRole.MANAGER)
    res = await client.get("/api/v1/audit")
    assert res.status_code == 200
    body = res.json()
    assert {"items", "total", "limit", "offset"} <= body.keys()


# ── Query ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_returns_recorded_entry(
    client: AsyncClient, auth_as: Callable[..., User], db_session: AsyncSession
) -> None:
    auth_as(UserRole.MANAGER)
    resource_id = uuid.uuid4()
    await AuditService(db_session).record(
        action=AuditAction.ALERT_CREATED,
        actor_type=AuditActorType.AGENT,
        actor_label="e_watchdog",
        resource_type="alert",
        resource_id=resource_id,
    )

    # Filter by the unique resource id so the assertion is immune to rows left by
    # other tests (record commits).
    res = await client.get("/api/v1/audit", params={"resource_id": str(resource_id)})
    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 1
    assert body["items"][0]["action"] == "alert.created"
    assert body["items"][0]["resource_id"] == str(resource_id)


# ── Integration ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_resolving_alert_writes_audit_row(
    client: AsyncClient, auth_as: Callable[..., User], db_session: AsyncSession
) -> None:
    user = auth_as(UserRole.MANAGER)
    # The resolve endpoint writes an audit row whose actor_id FKs to users, so the
    # acting user must exist in the DB (as it does in production).
    db_session.add(user)
    await db_session.commit()

    # Seed an alert directly, then resolve it through the API.
    alert = await AlertService(db_session).create_alert(
        AlertCreate(
            type=AlertType.ANOMALY,
            severity=AlertSeverity.WARNING,
            title="spike",
            body="unusual spend",
        )
    )

    res = await client.post(
        f"/api/v1/alerts/{alert.id}/resolve", json={"resolution_note": "reviewed"}
    )
    assert res.status_code == 200
    assert res.json()["status"] == AlertStatus.RESOLVED.value

    # Exactly one alert.resolved row attributed to the resolving manager.
    audit = await client.get(
        "/api/v1/audit", params={"resource_id": str(alert.id), "action": "alert.resolved"}
    )
    assert audit.status_code == 200
    body = audit.json()
    assert body["total"] == 1
    entry = body["items"][0]
    assert entry["actor_id"] == str(user.id)
    assert entry["outcome"] == "success"
    assert entry["metadata_payload"]["resolution_note"] == "reviewed"
