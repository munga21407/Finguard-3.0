"""Seed-users credential validation + plan assembly (hermetic, no DB).

The DB write path (create missing accounts, skip existing) needs Postgres and is
covered by an integration test; the security-critical pure logic — rejecting
weak/placeholder passwords in production and mapping env vars to OWNER/ADMIN
specs — is verified here.
"""
from __future__ import annotations

import pytest

from scripts import seed_users
from scripts.seed_users import (
    SeedConfigError,
    build_seed_specs,
    validate_seed_password,
)
from src.domains.identity.models import UserRole


def test_empty_password_rejected_in_any_environment() -> None:
    with pytest.raises(SeedConfigError):
        validate_seed_password("", is_production=False, label="owner")
    with pytest.raises(SeedConfigError):
        validate_seed_password("", is_production=True, label="owner")


@pytest.mark.parametrize("weak", ["short", "password123", "Change-Me-Now", "admin123!!"])
def test_weak_password_rejected_in_production(weak: str) -> None:
    with pytest.raises(SeedConfigError):
        validate_seed_password(weak, is_production=True, label="owner")


def test_weak_password_allowed_outside_production() -> None:
    # Dev/CID frictionless: any non-empty password is accepted off-production.
    validate_seed_password("x", is_production=False, label="owner")


def test_strong_password_accepted_in_production() -> None:
    validate_seed_password("Str0ng-Passphrase!42", is_production=True, label="owner")


def test_build_specs_maps_roles_and_lowercases_email(monkeypatch) -> None:
    monkeypatch.setattr(seed_users.settings, "SEED_OWNER_EMAIL", "Owner@Finguard.IO")
    monkeypatch.setattr(seed_users.settings, "SEED_OWNER_PASSWORD", "Str0ng-Owner-Pass!")
    monkeypatch.setattr(seed_users.settings, "SEED_ADMIN_EMAIL", "Admin@Finguard.IO")
    monkeypatch.setattr(seed_users.settings, "SEED_ADMIN_PASSWORD", "Str0ng-Admin-Pass!")

    specs = build_seed_specs(is_production=True)
    by_role = {s.role: s for s in specs}
    assert by_role[UserRole.OWNER].email == "owner@finguard.io"
    assert by_role[UserRole.ADMIN].email == "admin@finguard.io"
    assert set(by_role) == {UserRole.OWNER, UserRole.ADMIN}


def test_blank_email_role_is_skipped_not_errored(monkeypatch) -> None:
    monkeypatch.setattr(seed_users.settings, "SEED_OWNER_EMAIL", "owner@finguard.io")
    monkeypatch.setattr(seed_users.settings, "SEED_OWNER_PASSWORD", "Str0ng-Owner-Pass!")
    monkeypatch.setattr(seed_users.settings, "SEED_ADMIN_EMAIL", "")  # admin disabled
    monkeypatch.setattr(seed_users.settings, "SEED_ADMIN_PASSWORD", "")

    specs = build_seed_specs(is_production=True)
    assert [s.role for s in specs] == [UserRole.OWNER]


def test_configured_email_with_bad_password_raises(monkeypatch) -> None:
    monkeypatch.setattr(seed_users.settings, "SEED_OWNER_EMAIL", "owner@finguard.io")
    monkeypatch.setattr(seed_users.settings, "SEED_OWNER_PASSWORD", "weak")
    monkeypatch.setattr(seed_users.settings, "SEED_ADMIN_EMAIL", "")
    monkeypatch.setattr(seed_users.settings, "SEED_ADMIN_PASSWORD", "")

    with pytest.raises(SeedConfigError):
        build_seed_specs(is_production=True)
