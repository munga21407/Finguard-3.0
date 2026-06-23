"""
One-time migration: re-sign legacy HS256 Verifiable Credentials with Ed25519.

Why
---
Audit VCs in ``trust_log`` used to be JWTs signed with HS256 over the symmetric
``SECRET_KEY``. The verifier kept an HS256 fallback for backward compatibility,
which meant anyone who learned ``SECRET_KEY`` could forge a "legacy" VC and
poison the tamper-evident audit trail — defeating the whole point of the Ed25519
internal CA. The fallback has been removed from ``vc_issuer._decode_vc`` (see
``HS256_VC_SUNSET``); this script re-signs the pre-sunset entries so they remain
verifiable under the asymmetric trust root, then those documents are EdDSA-only.

What it does
------------
For every ``trust_log`` document whose ``vc_token`` is HS256-signed:
  1. Verifies the HMAC signature with ``SECRET_KEY`` (signature only — expiry is
     NOT enforced, so authentic-but-expired audit VCs are preserved, not dropped).
  2. Re-signs the *verified* claims with the CA Ed25519 key via ``_encode_vc``.
  3. Replaces ``vc_token`` and records provenance: ``migrated_from_alg``,
     ``migrated_at``, ``legacy_token_sha256`` (a fingerprint of the old token, so
     auditors can prove exactly what was replaced without retaining the forgeable
     artifact).

Tokens that fail HMAC verification are NOT re-signed (a compromised/forged token
must never be laundered into an Ed25519 signature); they are tagged
``migration_status="invalid_hs256_signature"`` for investigation. Already-EdDSA
documents are skipped, so the migration is idempotent and safe to re-run.

``SECRET_KEY`` is consulted here, deliberately and exactly once per token, by an
operator running this migration — never again at verification time.

Usage (from backend/):
    python -m scripts.migrate_hs256_vcs --dry-run     # report only, no writes
    python -m scripts.migrate_hs256_vcs               # apply
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
import logging
from datetime import UTC, datetime
from typing import Any

from jose import JWTError, jwt

from src.core.config import settings
from src.domains.intelligence.security.vc_issuer import COLLECTION, _encode_vc
from src.infrastructure.database.mongodb import close_mongo, get_mongo_db, init_mongo

logger = logging.getLogger("migrate_hs256_vcs")


def token_alg(token: str) -> str | None:
    """Return the ``alg`` from a compact token's header, or ``None`` if unparseable."""
    parts = token.split(".")
    if len(parts) != 3:
        return None
    try:
        header_seg = parts[0]
        padding = "=" * (-len(header_seg) % 4)
        header = json.loads(base64.urlsafe_b64decode(header_seg + padding))
    except (ValueError, json.JSONDecodeError):
        return None
    alg = header.get("alg")
    return alg if isinstance(alg, str) else None


def resign_hs256_token(legacy_token: str, secret_key: str) -> tuple[str, dict[str, Any]]:
    """Verify an HS256 VC and return ``(new_eddsa_token, claims)``.

    Signature is verified against ``secret_key``; expiry is intentionally NOT
    enforced so authentic-but-expired audit VCs are preserved with their original
    ``exp`` intact (the re-signed token stays expired — re-signing changes the
    algorithm, never the validity window).

    Raises:
        ValueError — the token is not HS256, or its HMAC signature is invalid.
    """
    if token_alg(legacy_token) != "HS256":
        raise ValueError("Token is not HS256-signed")
    try:
        claims: dict[str, Any] = jwt.decode(
            legacy_token,
            secret_key,
            algorithms=["HS256"],
            options={"verify_exp": False, "verify_aud": False},
        )
    except JWTError as exc:
        raise ValueError(f"HS256 signature verification failed: {exc}") from exc
    return _encode_vc(claims), claims


def _legacy_fingerprint(legacy_token: str) -> str:
    return hashlib.sha256(legacy_token.encode("utf-8")).hexdigest()


async def migrate(*, dry_run: bool) -> dict[str, int]:
    """Walk ``trust_log`` and re-sign every HS256 VC. Returns summary counts."""
    db = get_mongo_db()
    collection = db[COLLECTION]

    counts = {
        "scanned": 0,
        "migrated": 0,
        "already_eddsa": 0,
        "invalid_signature": 0,
        "no_token": 0,
        "unknown_alg": 0,
    }

    cursor = collection.find({})
    async for doc in cursor:
        counts["scanned"] += 1
        token = doc.get("vc_token")
        if not isinstance(token, str) or not token:
            counts["no_token"] += 1
            continue

        alg = token_alg(token)
        if alg == "EdDSA":
            counts["already_eddsa"] += 1
            continue
        if alg != "HS256":
            counts["unknown_alg"] += 1
            logger.warning("Skipping doc %s: unexpected alg %r", doc.get("_id"), alg)
            continue

        try:
            new_token, _claims = resign_hs256_token(token, settings.SECRET_KEY)
        except ValueError as exc:
            counts["invalid_signature"] += 1
            logger.error("Doc %s: %s — NOT re-signing", doc.get("_id"), exc)
            if not dry_run:
                await collection.update_one(
                    {"_id": doc["_id"]},
                    {"$set": {"migration_status": "invalid_hs256_signature"}},
                )
            continue

        if not dry_run:
            await collection.update_one(
                {"_id": doc["_id"]},
                {
                    "$set": {
                        "vc_token": new_token,
                        "migrated_from_alg": "HS256",
                        "migrated_at": datetime.now(UTC),
                        "legacy_token_sha256": _legacy_fingerprint(token),
                    }
                },
            )
        counts["migrated"] += 1

    return counts


async def _amain(dry_run: bool) -> None:
    await init_mongo()
    try:
        counts = await migrate(dry_run=dry_run)
    finally:
        await close_mongo()

    mode = "DRY-RUN (no writes)" if dry_run else "APPLIED"
    logger.info("HS256→Ed25519 VC migration complete [%s]", mode)
    for key, value in counts.items():
        logger.info("  %-18s %d", key, value)
    if counts["invalid_signature"]:
        logger.warning(
            "%d VC(s) failed HMAC verification and were left unsigned — investigate.",
            counts["invalid_signature"],
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would change without writing to trust_log.",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    asyncio.run(_amain(args.dry_run))


if __name__ == "__main__":
    main()
