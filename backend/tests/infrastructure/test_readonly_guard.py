"""
The read-only DB URL must be mandatory in production (fail closed), while local
dev falls back to the main engine with a warning.
"""
from __future__ import annotations

import pytest

from src.infrastructure.database import postgres


def test_readonly_url_required_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(postgres.settings, "DATABASE_READONLY_URL", "")
    monkeypatch.setattr(postgres.settings, "ENVIRONMENT", "production")
    with pytest.raises(RuntimeError, match="DATABASE_READONLY_URL must be set"):
        postgres._resolve_readonly_url()


def test_readonly_url_falls_back_outside_production(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(postgres.settings, "DATABASE_READONLY_URL", "")
    monkeypatch.setattr(postgres.settings, "ENVIRONMENT", "development")
    assert postgres._resolve_readonly_url() == postgres.settings.DATABASE_URL


def test_readonly_url_used_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    ro = "postgresql+asyncpg://finguard_readonly:pw@localhost:5432/finguard"
    monkeypatch.setattr(postgres.settings, "DATABASE_READONLY_URL", ro)
    monkeypatch.setattr(postgres.settings, "ENVIRONMENT", "production")
    assert postgres._resolve_readonly_url() == ro
