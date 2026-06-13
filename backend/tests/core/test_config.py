"""
Production configuration must fail fast on unsafe values; dev stays lenient.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.core.config import Settings

_BASE = {
    "DATABASE_URL": "postgresql+asyncpg://u:p@h:5432/finguard",
    "MONGODB_URL": "mongodb://h:27017",
    "REDIS_URL": "redis://h:6379/0",
    "RABBITMQ_URL": "amqp://h:5672/",
}

_STRONG_SECRET = "x" * 40
_RO_URL = "postgresql+asyncpg://finguard_readonly:pw@h:5432/finguard"
_METRICS = "m" * 32


def _settings(**over: object) -> Settings:
    return Settings(**{**_BASE, **over})  # type: ignore[arg-type]


def test_dev_allows_placeholder_secret() -> None:
    s = _settings(ENVIRONMENT="development", SECRET_KEY="change-me")
    assert s.ENVIRONMENT == "development"


def test_production_valid_config_boots() -> None:
    s = _settings(
        ENVIRONMENT="production",
        SECRET_KEY=_STRONG_SECRET,
        DEBUG=False,
        DATABASE_READONLY_URL=_RO_URL,
        METRICS_AUTH_SECRET=_METRICS,
        ALLOWED_ORIGINS=["https://app.finguard.io"],
    )
    assert s.ENVIRONMENT == "production"


@pytest.mark.parametrize(
    "override",
    [
        {"SECRET_KEY": "change-me-to-a-strong-random-secret-key"},  # placeholder
        {"SECRET_KEY": "short"},                                    # too short
        {"DEBUG": True},
        {"DATABASE_READONLY_URL": ""},
        {"METRICS_AUTH_SECRET": ""},
        {"ALLOWED_ORIGINS": ["*"]},
    ],
)
def test_production_rejects_unsafe_config(override: dict) -> None:
    base = {
        "ENVIRONMENT": "production",
        "SECRET_KEY": _STRONG_SECRET,
        "DEBUG": False,
        "DATABASE_READONLY_URL": _RO_URL,
        "METRICS_AUTH_SECRET": _METRICS,
        "ALLOWED_ORIGINS": ["https://app.finguard.io"],
    }
    base.update(override)
    with pytest.raises(ValidationError):
        _settings(**base)
