from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.logging import logger
from src.core.request_context import get_client_ip, get_request_id
from src.domains.audit.models import (
    AuditAction,
    AuditActorType,
    AuditLog,
    AuditOutcome,
)
from src.domains.audit.schemas import AuditKpis

if TYPE_CHECKING:
    from src.domains.identity.models import User


class AuditService:
    """Write and read the durable audit trail.

    Writes are append-only. ``record`` attaches request context (ip, request id)
    automatically from :mod:`src.core.request_context`, so call sites only supply
    the business facts (who, what action, which resource).
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ── write ────────────────────────────────────────────────────────────────

    async def record(
        self,
        *,
        action: AuditAction | str,
        actor_type: AuditActorType,
        resource_type: str,
        actor_id: uuid.UUID | None = None,
        actor_label: str | None = None,
        resource_id: str | uuid.UUID | None = None,
        outcome: AuditOutcome = AuditOutcome.SUCCESS,
        metadata: dict[str, Any] | None = None,
    ) -> AuditLog:
        """Persist one audit entry and return it.

        Commits its own row: audit rows are recorded *after* the business action
        they describe has succeeded, so a recorded entry always reflects a real
        event. May raise on a DB error — wrap with :meth:`record_safe` at call
        sites where audit failure must never break the primary action.
        """
        entry = AuditLog(
            action=str(action),
            actor_type=actor_type,
            actor_id=actor_id,
            actor_label=actor_label,
            resource_type=resource_type,
            resource_id=str(resource_id) if resource_id is not None else None,
            outcome=outcome,
            metadata_payload=metadata or {},
            ip_address=get_client_ip(),
            request_id=get_request_id(),
        )
        self._session.add(entry)
        await self._session.commit()
        await self._session.refresh(entry)
        return entry

    async def record_user_action(
        self,
        user: User,
        action: AuditAction | str,
        resource_type: str,
        *,
        resource_id: str | uuid.UUID | None = None,
        outcome: AuditOutcome = AuditOutcome.SUCCESS,
        metadata: dict[str, Any] | None = None,
    ) -> AuditLog:
        """Convenience wrapper for the common "an authenticated user did X" case."""
        return await self.record(
            action=action,
            actor_type=AuditActorType.USER,
            actor_id=user.id,
            actor_label=user.email,
            resource_type=resource_type,
            resource_id=resource_id,
            outcome=outcome,
            metadata=metadata,
        )

    async def record_user_action_safe(
        self,
        user: User,
        action: AuditAction | str,
        resource_type: str,
        *,
        resource_id: str | uuid.UUID | None = None,
        outcome: AuditOutcome = AuditOutcome.SUCCESS,
        metadata: dict[str, Any] | None = None,
    ) -> AuditLog | None:
        """Best-effort "an authenticated user did X" — never raises.

        The boilerplate-free helper for instrumenting state-mutating endpoints:
        call it *after* the business action has committed so a missing audit row
        can never turn a successful action into a 500. Combines
        :meth:`record_user_action`'s ergonomics with :meth:`record_safe`'s
        failure isolation.
        """
        return await self.record_safe(
            action=action,
            actor_type=AuditActorType.USER,
            actor_id=user.id,
            actor_label=user.email,
            resource_type=resource_type,
            resource_id=resource_id,
            outcome=outcome,
            metadata=metadata,
        )

    async def record_safe(
        self,
        *,
        action: AuditAction | str,
        actor_type: AuditActorType,
        resource_type: str,
        actor_id: uuid.UUID | None = None,
        actor_label: str | None = None,
        resource_id: str | uuid.UUID | None = None,
        outcome: AuditOutcome = AuditOutcome.SUCCESS,
        metadata: dict[str, Any] | None = None,
    ) -> AuditLog | None:
        """Best-effort :meth:`record` — never raises.

        Use after a business action has already committed, where failing to write
        the audit row must not turn a successful action into a 500. The failure is
        logged (and surfaces in operational logs/metrics) rather than swallowed
        silently.
        """
        try:
            return await self.record(
                action=action,
                actor_type=actor_type,
                resource_type=resource_type,
                actor_id=actor_id,
                actor_label=actor_label,
                resource_id=resource_id,
                outcome=outcome,
                metadata=metadata,
            )
        except Exception as exc:  # noqa: BLE001 — audit must not break the primary action
            await self._session.rollback()
            logger.error(
                "audit_record_failed",
                action=str(action),
                resource_type=resource_type,
                resource_id=str(resource_id) if resource_id is not None else None,
                error=repr(exc),
            )
            return None

    # ── read ─────────────────────────────────────────────────────────────────

    async def query(
        self,
        *,
        actor_id: uuid.UUID | None = None,
        action: str | None = None,
        resource_type: str | None = None,
        resource_id: str | None = None,
        outcome: AuditOutcome | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[AuditLog], int]:
        """Return a filtered, most-recent-first page plus the total match count."""
        filters = []
        if actor_id is not None:
            filters.append(AuditLog.actor_id == actor_id)
        if action is not None:
            filters.append(AuditLog.action == action)
        if resource_type is not None:
            filters.append(AuditLog.resource_type == resource_type)
        if resource_id is not None:
            filters.append(AuditLog.resource_id == resource_id)
        if outcome is not None:
            filters.append(AuditLog.outcome == outcome)
        if since is not None:
            filters.append(AuditLog.created_at >= since)
        if until is not None:
            filters.append(AuditLog.created_at <= until)

        total = (
            await self._session.scalar(
                select(func.count()).select_from(AuditLog).where(*filters)
            )
        ) or 0

        stmt = (
            select(AuditLog)
            .where(*filters)
            .order_by(AuditLog.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all()), total

    async def kpis(self) -> AuditKpis:
        day_ago = datetime.now(UTC) - timedelta(hours=24)

        total = (await self._session.scalar(select(func.count()).select_from(AuditLog))) or 0
        last_24h = (
            await self._session.scalar(
                select(func.count()).select_from(AuditLog).where(AuditLog.created_at >= day_ago)
            )
        ) or 0
        failures = (
            await self._session.scalar(
                select(func.count())
                .select_from(AuditLog)
                .where(AuditLog.created_at >= day_ago, AuditLog.outcome == AuditOutcome.FAILURE)
            )
        ) or 0
        denied = (
            await self._session.scalar(
                select(func.count())
                .select_from(AuditLog)
                .where(AuditLog.created_at >= day_ago, AuditLog.outcome == AuditOutcome.DENIED)
            )
        ) or 0

        return AuditKpis(
            total=total,
            last_24h=last_24h,
            failures_last_24h=failures,
            denied_last_24h=denied,
        )
