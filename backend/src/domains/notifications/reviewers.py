"""Fan-out an approval notification to everyone allowed to review an item.

Shared by the payable queue (finance) and the agent-action queue (intelligence):
resolve the users whose role grants the reviewing permission, drop the person who
raised the item (they can't review their own — segregation of duties), and enqueue
one idempotency-keyed email each. Enqueue-only, so it rides the caller's
transaction.

``notifications`` is an ungoverned domain (not in the architecture isolation
rules), so importing ``identity`` here is allowed and creates no cycle —
``identity`` never imports this module.
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.core.security import create_unsubscribe_token
from src.domains.identity.permissions import Permission, roles_with_permission
from src.domains.identity.repository import UserRepository
from src.domains.notifications.models import EmailCategory
from src.domains.notifications.service import NotificationService


def unsubscribe_url(email: str, category: EmailCategory) -> str:
    """Absolute one-click unsubscribe link for an email's footer / List-Unsubscribe."""
    token = create_unsubscribe_token(email, category.value)
    return f"{settings.APP_BASE_URL}/api/v1/notifications/unsubscribe?token={token}"


async def notify_reviewers(
    session: AsyncSession,
    *,
    permission: Permission,
    subject: str,
    template: str,
    context: dict[str, Any],
    resource_id: uuid.UUID | str,
    key_prefix: str,
    exclude_user_id: uuid.UUID | None = None,
) -> int:
    """Enqueue an approval email to each eligible reviewer. Returns the count sent.

    Idempotency key is ``{key_prefix}:{resource_id}:{user_id}`` so re-triggering
    (or a resubmit) never double-notifies a given reviewer for a given item.
    """
    roles = roles_with_permission(permission)
    reviewers = await UserRepository(session).list_active_by_roles(roles)
    svc = NotificationService(session)

    enqueued = 0
    for user in reviewers:
        if exclude_user_id is not None and user.id == exclude_user_id:
            continue  # the requester can't review their own item
        did = await svc.enqueue_email(
            to_email=user.email,
            to_name=user.full_name,
            subject=subject,
            template=template,
            context={
                **context,
                "reviewer_name": user.full_name,
                "unsubscribe_url": unsubscribe_url(user.email, EmailCategory.APPROVAL),
            },
            idempotency_key=f"{key_prefix}:{resource_id}:{user.id}",
            category=EmailCategory.APPROVAL,
        )
        if did:
            enqueued += 1
    return enqueued
