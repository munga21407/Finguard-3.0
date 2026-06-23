"""AuditService write/read behaviour against the live test database.

Covers the append-only write path (``record`` / ``record_user_action``), the
failure-isolation contract of ``record_safe``, and the filtered ``query`` + KPI
aggregation that back the activity-log API.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from src.domains.audit.models import AuditAction, AuditActorType, AuditLog, AuditOutcome
from src.domains.audit.service import AuditService
from src.domains.identity.models import User, UserRole


async def _clear(db: AsyncSession) -> None:
    """Reset the append-only table so count-based assertions are deterministic
    (``record`` commits, so rows otherwise leak across tests)."""
    await db.execute(delete(AuditLog))
    await db.commit()


def _user() -> User:
    return User(
        id=uuid.uuid4(),
        email=f"actor-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
        full_name="Actor",
        role=UserRole.MANAGER,
        is_active=True,
        is_verified=True,
    )


@pytest.mark.asyncio
async def test_record_user_action_persists_fields(db_session: AsyncSession) -> None:
    user = _user()
    # actor_id is a real FK to users — persist the actor first, as it always is in
    # production (the actor is the authenticated, DB-resident current_user).
    db_session.add(user)
    await db_session.commit()
    resource_id = uuid.uuid4()

    entry = await AuditService(db_session).record_user_action(
        user,
        AuditAction.ALERT_RESOLVED,
        "alert",
        resource_id=resource_id,
        metadata={"resolution_note": "looks fine"},
    )

    assert entry.actor_type == AuditActorType.USER
    assert entry.actor_id == user.id
    assert entry.actor_label == user.email
    assert entry.action == "alert.resolved"
    assert entry.resource_type == "alert"
    assert entry.resource_id == str(resource_id)
    assert entry.outcome == AuditOutcome.SUCCESS
    assert entry.metadata_payload == {"resolution_note": "looks fine"}
    assert entry.created_at is not None


@pytest.mark.asyncio
async def test_record_safe_swallows_failure(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = AuditService(db_session)

    async def _boom(*_args: object, **_kwargs: object) -> AuditLog:
        raise RuntimeError("db exploded")

    # record_safe delegates to record(); a failure there must be swallowed so the
    # primary business action is never turned into a 500.
    monkeypatch.setattr(service, "record", _boom)

    result = await service.record_safe(
        action=AuditAction.AUTH_LOGIN,
        actor_type=AuditActorType.USER,
        resource_type="session",
    )

    assert result is None


@pytest.mark.asyncio
async def test_query_filters_and_paginates(db_session: AsyncSession) -> None:
    await _clear(db_session)
    service = AuditService(db_session)

    for _ in range(3):
        await service.record(
            action=AuditAction.ALERT_CREATED,
            actor_type=AuditActorType.AGENT,
            actor_label="e_watchdog",
            resource_type="alert",
        )
    await service.record(
        action=AuditAction.AUTH_LOGIN_FAILED,
        actor_type=AuditActorType.USER,
        actor_label="probe@example.com",
        resource_type="session",
        outcome=AuditOutcome.FAILURE,
    )

    # Filter by action.
    items, total = await service.query(action="alert.created")
    assert total == 3
    assert all(i.action == "alert.created" for i in items)

    # Filter by outcome.
    failures, fail_total = await service.query(outcome=AuditOutcome.FAILURE)
    assert fail_total == 1
    assert failures[0].action == "auth.login_failed"

    # Pagination: limit caps the page but total reflects the full match set.
    page, page_total = await service.query(action="alert.created", limit=2, offset=0)
    assert page_total == 3
    assert len(page) == 2


@pytest.mark.asyncio
async def test_kpis_counts_recent_outcomes(db_session: AsyncSession) -> None:
    await _clear(db_session)
    service = AuditService(db_session)

    await service.record(
        action=AuditAction.AUTH_LOGIN,
        actor_type=AuditActorType.USER,
        actor_label="ok@example.com",
        resource_type="session",
    )
    await service.record(
        action=AuditAction.AUTH_LOGIN_FAILED,
        actor_type=AuditActorType.USER,
        actor_label="bad@example.com",
        resource_type="session",
        outcome=AuditOutcome.FAILURE,
    )

    kpis = await service.kpis()
    assert kpis.total == 2
    # Freshly inserted rows are all within the trailing 24h window.
    assert kpis.last_24h == 2
    assert kpis.failures_last_24h == 1
    assert kpis.denied_last_24h == 0
