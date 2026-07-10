"""API schemas for notification preferences + email delivery admin."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel

from src.domains.notifications.models import EmailCategory, EmailStatus


class CategoryPreference(BaseModel):
    """A single suppressible category and whether the user has opted out."""

    category: EmailCategory
    label: str
    opted_out: bool


class PreferencesResponse(BaseModel):
    """The current user's email preferences (suppressible categories only)."""

    preferences: list[CategoryPreference]


class PreferenceUpdate(BaseModel):
    category: EmailCategory
    opted_out: bool


# ── Email delivery admin ──────────────────────────────────────────────────────

class EmailOutboxItem(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    to_email: str
    subject: str
    template: str
    status: EmailStatus
    attempts: int
    last_error: str | None = None
    sent_at: datetime | None = None
    created_at: datetime


class EmailOutboxPage(BaseModel):
    items: list[EmailOutboxItem]
    total: int
    limit: int
    offset: int


class EmailDeadLetterItem(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    to_email: str
    subject: str
    template: str
    attempts: int
    last_error: str | None = None
    dead_lettered_at: datetime


class EmailDeadLetterPage(BaseModel):
    items: list[EmailDeadLetterItem]
    total: int
    limit: int
    offset: int


class EmailKpis(BaseModel):
    pending: int
    sent: int
    failed: int
    dead_lettered: int
