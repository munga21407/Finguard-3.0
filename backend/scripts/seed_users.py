"""
Seed the initial superuser (OWNER) + ADMIN accounts.

Lets an operator log in on a fresh deploy without self-registering through the
bootstrap-key flow. Reads credentials from the ``SEED_*`` settings (env vars):

    SEED_OWNER_EMAIL / SEED_OWNER_PASSWORD / SEED_OWNER_NAME
    SEED_ADMIN_EMAIL / SEED_ADMIN_PASSWORD / SEED_ADMIN_NAME

Both seeded accounts are created **verified + active** with their role, so they
can authenticate immediately. A role whose email is blank is simply skipped.

Idempotent: an account whose email already exists is left untouched (re-running
never resets a rotated password or downgrades a role). Safe to run on every
deploy.

In ``ENVIRONMENT=production`` the seeder refuses to create an account with a
weak/placeholder password (mirrors the SECRET_KEY / INITIAL_BOOTSTRAP_KEY
fail-fast guards) so a real deployment can't ship a guessable admin.

Usage (from backend/):
    python -m scripts.seed_users            # create missing seed accounts
    python -m scripts.seed_users --dry-run  # report what would be created
"""
from __future__ import annotations

import argparse
import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from src.core.config import settings
from src.core.security import hash_password
from src.domains.identity.models import User, UserRole
from src.domains.identity.repository import UserRepository
from src.infrastructure.database.postgres import AsyncSessionLocal

logger = logging.getLogger("seed_users")

# Minimum length + obvious placeholders rejected for a seeded password in prod.
_MIN_PASSWORD_LEN = 12
_PLACEHOLDER_FRAGMENTS = (
    "change-me",
    "changeme",
    "password",
    "secret",
    "admin123",
    "letmein",
)


@dataclass(frozen=True)
class SeedSpec:
    """A planned seed account."""

    role: UserRole
    email: str
    password: str
    full_name: str


class SeedConfigError(ValueError):
    """Raised when a seed account is configured with an unusable credential."""


def validate_seed_password(password: str, *, is_production: bool, label: str) -> None:
    """Reject an empty (always) or weak/placeholder (production-only) password.

    Outside production, only a blank password is rejected so local dev / CI stay
    frictionless. In production the password must be reasonably long and free of
    obvious placeholder fragments.
    """
    if not password:
        raise SeedConfigError(f"{label}: password must not be empty")
    if not is_production:
        return
    if len(password) < _MIN_PASSWORD_LEN:
        raise SeedConfigError(
            f"{label}: password must be at least {_MIN_PASSWORD_LEN} characters in production"
        )
    lowered = password.lower()
    if any(frag in lowered for frag in _PLACEHOLDER_FRAGMENTS):
        raise SeedConfigError(f"{label}: password looks like a placeholder — choose a strong one")


def build_seed_specs(*, is_production: bool) -> list[SeedSpec]:
    """Assemble the seed plan from settings, validating each configured account.

    A role with a blank email is skipped (not an error). A role with an email but
    a bad password raises ``SeedConfigError`` so misconfiguration fails loudly.
    """
    raw = [
        (
            UserRole.OWNER,
            settings.SEED_OWNER_EMAIL.strip(),
            settings.SEED_OWNER_PASSWORD,
            settings.SEED_OWNER_NAME,
        ),
        (
            UserRole.ADMIN,
            settings.SEED_ADMIN_EMAIL.strip(),
            settings.SEED_ADMIN_PASSWORD,
            settings.SEED_ADMIN_NAME,
        ),
    ]
    specs: list[SeedSpec] = []
    for role, email, password, name in raw:
        if not email:
            continue
        validate_seed_password(password, is_production=is_production, label=role.value)
        specs.append(SeedSpec(role=role, email=email.lower(), password=password, full_name=name))
    return specs


async def seed(*, dry_run: bool) -> dict[str, int]:
    """Create any missing seed accounts. Existing emails are left untouched."""
    is_production = settings.ENVIRONMENT == "production"
    specs = build_seed_specs(is_production=is_production)

    if not specs:
        logger.warning(
            "No seed accounts configured — set SEED_OWNER_EMAIL / SEED_ADMIN_EMAIL "
            "(and matching passwords) to enable seeding."
        )
        return {"created": 0, "skipped_existing": 0, "configured": 0}

    created = 0
    skipped = 0
    async with AsyncSessionLocal() as session:
        repo = UserRepository(session)
        for spec in specs:
            if await repo.get_by_email(spec.email) is not None:
                logger.info("Seed %s already exists — skipping", spec.email)
                skipped += 1
                continue
            if dry_run:
                logger.info(
                    "[dry-run] would create %s account: %s", spec.role.value, spec.email
                )
                created += 1
                continue
            await repo.create(
                User(
                    email=spec.email,
                    hashed_password=hash_password(spec.password),
                    full_name=spec.full_name,
                    role=spec.role,
                    is_active=True,
                    is_verified=True,
                    # Seeded first-login accounts skip email verification too — both
                    # login gates are satisfied so they can sign in immediately.
                    email_verified_at=datetime.now(UTC),
                )
            )
            logger.info("Created %s account: %s", spec.role.value, spec.email)
            created += 1
        if not dry_run:
            await session.commit()

    return {"created": created, "skipped_existing": skipped, "configured": len(specs)}


async def _amain(dry_run: bool) -> None:
    result = await seed(dry_run=dry_run)
    mode = "DRY-RUN (no writes)" if dry_run else "APPLIED"
    logger.info(
        "Seed complete [%s]: %d created, %d already existed (of %d configured)",
        mode,
        result["created"],
        result["skipped_existing"],
        result["configured"],
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would be created without writing to the database.",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        asyncio.run(_amain(args.dry_run))
    except SeedConfigError as exc:
        logger.error("Seed aborted: %s", exc)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
