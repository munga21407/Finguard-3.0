"""
Verifiable Credential (VC) issuer for AI agent audit trails.

Each VC is a tamper-evident JWT-signed record that proves:
  - which agent performed an operation
  - what the operation was and when it ran
  - a SHA-256 hash of the operation payload (for data integrity)

VCs are written asynchronously to the MongoDB `trust_log` collection
BEFORE an alert action resolves, satisfying SOC-2 / compliance requirements.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any

from jose import jwt

from src.core.config import settings
from src.domains.intelligence.security.agent_cards import get_card
from src.infrastructure.database.mongodb import get_mongo_db

COLLECTION = "trust_log"
VC_TTL_DAYS = 365  # retain credentials for one year


def _payload_hash(payload: dict[str, Any]) -> str:
    """SHA-256 fingerprint of a JSON payload, key-sorted for determinism."""
    canonical = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def _build_vc_claims(
    agent_id: str,
    operation: str,
    operation_summary: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    card = get_card(agent_id)
    now = datetime.now(timezone.utc)
    return {
        # Standard JWT claims
        "iss": card.issuer,
        "sub": agent_id,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(days=VC_TTL_DAYS)).timestamp()),
        # Finguard VC-specific claims
        "agent_id": agent_id,
        "agent_name": card.name,
        "agent_version": card.version,
        "operation": operation,
        "operation_summary": operation_summary,
        "timestamp": now.isoformat(),
        "payload_hash": _payload_hash(payload),
    }


async def issue_vc(
    agent_id: str,
    operation: str,
    operation_summary: str,
    payload: dict[str, Any],
) -> str:
    """
    Create a signed VC, persist it to `trust_log`, and return the document ID.

    Args:
        agent_id:           Agent identifier (e.g. "E").
        operation:          Machine-readable operation key (e.g. "budget_watchdog").
        operation_summary:  Human-readable description for auditors.
        payload:            The data artifact the operation produced (hashed, not stored raw).

    Returns:
        MongoDB ObjectId string of the inserted trust_log document.
    """
    claims = _build_vc_claims(agent_id, operation, operation_summary, payload)
    token = jwt.encode(claims, settings.SECRET_KEY, algorithm="HS256")

    doc = {
        "vc_token": token,
        "claims": claims,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    db = get_mongo_db()
    result = await db[COLLECTION].insert_one(doc)
    return str(result.inserted_id)


def verify_vc(token: str) -> dict[str, Any]:
    """Decode and verify a VC token. Raises jose.JWTError on tampered/expired VCs."""
    return jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
