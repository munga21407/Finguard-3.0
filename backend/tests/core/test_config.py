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
_CA_KEY = "a" * 64  # 32-byte Ed25519 CA key, hex-encoded
_BOOTSTRAP = "b" * 40  # one-time OWNER bootstrap secret


def _settings(**over: object) -> Settings:
    # _env_file=None keeps these tests hermetic: without it pydantic-settings
    # leaks the repo `.env` (which carries sandbox M-Pesa keys, a real SECRET_KEY,
    # etc.) into every unset field, making the production-validation assertions
    # depend on whatever happens to be in `.env`.
    return Settings(_env_file=None, **{**_BASE, **over})  # type: ignore[arg-type]


def test_dev_allows_placeholder_secret() -> None:
    s = _settings(ENVIRONMENT="development", SECRET_KEY="change-me")
    assert s.ENVIRONMENT == "development"


def test_jwt_secret_defaults_to_secret_key() -> None:
    s = _settings(SECRET_KEY=_STRONG_SECRET)
    assert s.JWT_SECRET_KEY == _STRONG_SECRET


def test_jwt_secret_can_be_decoupled() -> None:
    s = _settings(SECRET_KEY=_STRONG_SECRET, JWT_SECRET_KEY="y" * 40)
    assert s.JWT_SECRET_KEY == "y" * 40
    assert s.JWT_SECRET_KEY != s.SECRET_KEY


def test_production_valid_config_boots() -> None:
    s = _settings(
        ENVIRONMENT="production",
        SECRET_KEY=_STRONG_SECRET,
        DEBUG=False,
        DATABASE_READONLY_URL=_RO_URL,
        METRICS_AUTH_SECRET=_METRICS,
        FINGUARD_CA_PRIVATE_KEY_HEX=_CA_KEY,
        INITIAL_BOOTSTRAP_KEY=_BOOTSTRAP,
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
        {"FINGUARD_CA_PRIVATE_KEY_HEX": ""},  # CA key required in production
        {"INITIAL_BOOTSTRAP_KEY": ""},                       # bootstrap key required
        {"INITIAL_BOOTSTRAP_KEY": "short"},                  # too weak
        {"INITIAL_BOOTSTRAP_KEY": "change-me-" + "x" * 30},  # placeholder (>=32 chars)
    ],
)
def test_production_rejects_unsafe_config(override: dict) -> None:
    base = {
        "ENVIRONMENT": "production",
        "SECRET_KEY": _STRONG_SECRET,
        "DEBUG": False,
        "DATABASE_READONLY_URL": _RO_URL,
        "METRICS_AUTH_SECRET": _METRICS,
        "FINGUARD_CA_PRIVATE_KEY_HEX": _CA_KEY,
        "INITIAL_BOOTSTRAP_KEY": _BOOTSTRAP,
        "ALLOWED_ORIGINS": ["https://app.finguard.io"],
    }
    base.update(override)
    with pytest.raises(ValidationError):
        _settings(**base)


_PROD_OK = {
    "ENVIRONMENT": "production",
    "SECRET_KEY": _STRONG_SECRET,
    "DEBUG": False,
    "DATABASE_READONLY_URL": _RO_URL,
    "METRICS_AUTH_SECRET": _METRICS,
    "FINGUARD_CA_PRIVATE_KEY_HEX": _CA_KEY,
    "INITIAL_BOOTSTRAP_KEY": _BOOTSTRAP,
    "ALLOWED_ORIGINS": ["https://app.finguard.io"],
}


def test_production_mpesa_enabled_requires_callback_allowlist() -> None:
    """A live M-Pesa deployment must pin the STK callback to Safaricom's IPs —
    the callback marks invoices paid and is otherwise unauthenticated."""
    with pytest.raises(ValidationError):
        _settings(
            **_PROD_OK,
            MPESA_CONSUMER_KEY="ck",
            MPESA_CONSUMER_SECRET="cs",
            MPESA_SHORTCODE="600000",
            # MPESA_CALLBACK_ALLOWED_IPS deliberately unset
        )


def test_production_mpesa_with_allowlist_boots() -> None:
    s = _settings(
        **_PROD_OK,
        MPESA_CONSUMER_KEY="ck",
        MPESA_CONSUMER_SECRET="cs",
        MPESA_SHORTCODE="600000",
        MPESA_CALLBACK_ALLOWED_IPS=["196.201.214.0/24"],
    )
    assert s.MPESA_CALLBACK_ALLOWED_IPS == ["196.201.214.0/24"]


def test_production_without_mpesa_does_not_require_allowlist() -> None:
    """M-Pesa is optional; a deployment that hasn't configured it needs no allowlist."""
    s = _settings(**_PROD_OK)
    assert s.MPESA_CALLBACK_ALLOWED_IPS == []
