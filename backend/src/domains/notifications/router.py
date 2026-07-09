"""Notification preferences + one-click unsubscribe.

Authenticated users manage their own suppressible-category opt-outs; the
unsubscribe endpoints are public (they authenticate via a signed token embedded in
the email link, so they work for external customers with no account).
"""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.security import create_unsubscribe_token, decode_unsubscribe_token
from src.domains.audit.models import AuditAction
from src.domains.audit.service import AuditService
from src.domains.identity.dependencies import CurrentUser, RequireUserManage
from src.domains.notifications.models import (
    SUPPRESSIBLE_CATEGORIES,
    EmailCategory,
    EmailStatus,
)
from src.domains.notifications.schemas import (
    CategoryPreference,
    EmailDeadLetterItem,
    EmailDeadLetterPage,
    EmailKpis,
    EmailOutboxItem,
    EmailOutboxPage,
    PreferencesResponse,
    PreferenceUpdate,
)
from src.domains.notifications.service import NotificationService
from src.infrastructure.database.postgres import get_db

router = APIRouter()

DBSession = Annotated[AsyncSession, Depends(get_db)]

_CATEGORY_LABELS = {
    EmailCategory.APPROVAL: "Approval requests",
    EmailCategory.REMINDER: "Payment reminders",
}


def _ordered_suppressible() -> list[EmailCategory]:
    return [c for c in EmailCategory if c in SUPPRESSIBLE_CATEGORIES]


@router.get("/preferences", response_model=PreferencesResponse)
async def get_preferences(current_user: CurrentUser, db: DBSession) -> PreferencesResponse:
    """The current user's email preferences (only categories that can be turned off)."""
    opted_out = await NotificationService(db).list_opt_outs(current_user.email)
    return PreferencesResponse(
        preferences=[
            CategoryPreference(
                category=cat,
                label=_CATEGORY_LABELS[cat],
                opted_out=cat in opted_out,
            )
            for cat in _ordered_suppressible()
        ]
    )


@router.put("/preferences", response_model=PreferencesResponse)
async def update_preference(
    data: PreferenceUpdate, current_user: CurrentUser, db: DBSession
) -> PreferencesResponse:
    """Turn a suppressible email category on or off for the current user."""
    svc = NotificationService(db)
    await svc.set_opt_out(current_user.email, data.category, opted_out=data.opted_out)
    return await get_preferences(current_user, db)


def _confirmation_page(message: str) -> HTMLResponse:
    body = (
        "font-family:system-ui,sans-serif;background:#f6f4fb;margin:0;"
        "padding:3rem 1rem;text-align:center;color:#1c1a26;"
    )
    card = (
        "max-width:420px;margin:0 auto;background:#fff;border-radius:14px;"
        "padding:2rem;box-shadow:0 8px 30px rgba(0,0,0,.06);"
    )
    brand = (
        "font-weight:700;color:#6b38d4;font-size:.8rem;letter-spacing:.1em;"
        "text-transform:uppercase;"
    )
    html = (
        '<!doctype html><html><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        "<title>Finguard email preferences</title></head>"
        f'<body style="{body}"><div style="{card}">'
        f'<div style="{brand}">Finguard</div>'
        f'<p style="font-size:1.05rem;margin:1rem 0 0;">{message}</p>'
        "</div></body></html>"
    )
    return HTMLResponse(content=html)


@router.get("/unsubscribe", response_class=HTMLResponse)
async def unsubscribe(db: DBSession, token: str = Query(...)) -> HTMLResponse:
    """Public unsubscribe landing (from an email link). Idempotent."""
    email, category = decode_unsubscribe_token(token)
    await NotificationService(db).set_opt_out(
        email, EmailCategory(category), opted_out=True
    )
    label = _CATEGORY_LABELS.get(EmailCategory(category), category)
    return _confirmation_page(
        f"You've been unsubscribed from {label}. You can re-enable this anytime in your settings."
    )


@router.post("/unsubscribe")
async def unsubscribe_one_click(db: DBSession, token: str = Query(...)) -> dict[str, str]:
    """RFC 8058 one-click unsubscribe (mail clients POST this). Idempotent."""
    email, category = decode_unsubscribe_token(token)
    await NotificationService(db).set_opt_out(
        email, EmailCategory(category), opted_out=True
    )
    return {"status": "unsubscribed"}


def build_unsubscribe_url(base_url: str, email: str, category: EmailCategory) -> str:
    """Absolute unsubscribe link for an email's List-Unsubscribe header / footer."""
    token = create_unsubscribe_token(email, category.value)
    return f"{base_url}/api/v1/notifications/unsubscribe?token={token}"


# ── Email delivery admin (user:manage) ────────────────────────────────────────

@router.get("/admin/email/kpis", response_model=EmailKpis)
async def email_kpis(db: DBSession, _: RequireUserManage) -> EmailKpis:
    """Outbox counts by status + dead-letter total for the ops dashboard."""
    return EmailKpis(**await NotificationService(db).kpis())


@router.get("/admin/email/outbox", response_model=EmailOutboxPage)
async def list_outbox(
    db: DBSession,
    _: RequireUserManage,
    status: EmailStatus | None = None,
    template: str | None = None,
    to_email: str | None = None,
    limit: int = Query(50, le=200),
    offset: int = 0,
) -> EmailOutboxPage:
    """Filtered, paginated outbox rows (most recent first)."""
    items, total = await NotificationService(db).list_outbox(
        status=status, template=template, to_email=to_email, limit=limit, offset=offset
    )
    return EmailOutboxPage(
        items=[EmailOutboxItem.model_validate(i) for i in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/admin/email/dead-letters", response_model=EmailDeadLetterPage)
async def list_dead_letters(
    db: DBSession,
    _: RequireUserManage,
    limit: int = Query(50, le=200),
    offset: int = 0,
) -> EmailDeadLetterPage:
    """Emails that exhausted their retries, awaiting inspection / replay."""
    items, total = await NotificationService(db).list_dead_letters(
        limit=limit, offset=offset
    )
    return EmailDeadLetterPage(
        items=[EmailDeadLetterItem.model_validate(i) for i in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("/admin/email/dead-letters/{dead_letter_id}/replay", status_code=202)
async def replay_dead_letter(
    dead_letter_id: uuid.UUID, db: DBSession, current_user: RequireUserManage
) -> dict[str, str]:
    """Re-queue a dead-lettered email for delivery."""
    row = await NotificationService(db).replay_dead_letter(dead_letter_id)
    await AuditService(db).record_user_action_safe(
        current_user, AuditAction.EMAIL_REPLAYED, "email",
        resource_id=row.id, metadata={"template": row.template, "to": row.to_email},
    )
    return {"status": "requeued", "email_id": str(row.id)}


@router.post("/admin/email/outbox/{email_id}/resend", status_code=202)
async def resend_email(
    email_id: uuid.UUID, db: DBSession, current_user: RequireUserManage
) -> dict[str, str]:
    """Re-send a delivered email as a fresh pending row."""
    row = await NotificationService(db).resend(email_id)
    await AuditService(db).record_user_action_safe(
        current_user, AuditAction.EMAIL_RESENT, "email",
        resource_id=row.id, metadata={"template": row.template, "to": row.to_email},
    )
    return {"status": "requeued", "email_id": str(row.id)}
