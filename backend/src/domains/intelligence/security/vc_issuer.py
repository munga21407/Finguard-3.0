"""
Verifiable Credential (VC) issuer for AI agent audit trails (Sprint 6).

Two credential types
---------------------
1. **Audit VCs** (``issue_vc``) — long-lived (365 days), written to ``trust_log``
   for SOC-2 / compliance requirements. Used by Agent E and other agents to record
   every significant operation in a tamper-evident audit trail.

2. **Task-scoped VCs** (``issue_task_scoped_vc``) — short-lived (5 minutes), bound
   to a specific ``transaction_id``. Agents MUST call ``validate_task_vc()`` before
   executing any database write to prove they hold a valid, in-scope credential for
   that exact transaction.

Both types are signed with HS256 using the application ``SECRET_KEY``. The agent_did
field from the CA-signed AgentCard is embedded so validators can cross-check identity.

Sprint 6 additions
-------------------
- ``issue_task_scoped_vc()`` — issues a VC with ``jti=transaction_id``, ``exp=now+5min``.
- ``validate_task_vc()``     — decodes, verifies, and enforces scope + agent binding.
- Audit VCs now embed ``agent_did`` from the signed AgentCard.
"""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any

from jose import JWTError, jwt

from src.core.config import settings
from src.core.logging import logger
from src.domains.intelligence.security.agent_cards import get_card
from src.infrastructure.database.mongodb import get_mongo_db

COLLECTION = "trust_log"
VC_TTL_DAYS = 365
TASK_VC_TTL_SECONDS = 300  # 5-minute hard TTL for task-scoped VCs


# ---------------------------------------------------------------------------
# Shared utilities
# ---------------------------------------------------------------------------

def _payload_hash(payload: dict[str, Any]) -> str:
    """SHA-256 fingerprint of a JSON payload, key-sorted for determinism."""
    canonical = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Audit VCs (long-lived, for compliance trail)
# ---------------------------------------------------------------------------

def _build_audit_vc_claims(
    agent_id: str,
    operation: str,
    operation_summary: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    card = get_card(agent_id)
    now = datetime.now(UTC)
    return {
        # Standard JWT claims
        "iss": card.issuer,
        "sub": agent_id,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(days=VC_TTL_DAYS)).timestamp()),
        # Finguard VC-specific claims
        "vc_type": "audit",
        "agent_id": agent_id,
        "agent_name": card.name,
        "agent_version": card.version,
        "agent_did": card.did,
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
    Create a signed audit VC, persist it to ``trust_log``, and return the document ID.

    Args:
        agent_id:           Agent identifier (e.g. "E").
        operation:          Machine-readable operation key (e.g. "budget_watchdog_audit").
        operation_summary:  Human-readable description for auditors.
        payload:            The data artifact produced (SHA-256 hashed, not stored raw).

    Returns:
        MongoDB ObjectId string of the inserted trust_log document.
    """
    claims = _build_audit_vc_claims(agent_id, operation, operation_summary, payload)
    token = jwt.encode(claims, settings.SECRET_KEY, algorithm="HS256")

    doc = {
        "vc_token": token,
        "claims": claims,
        "vc_type": "audit",
        "created_at": datetime.now(UTC).isoformat(),
    }

    db = get_mongo_db()
    result = await db[COLLECTION].insert_one(doc)
    return str(result.inserted_id)


def verify_vc(token: str) -> dict[str, Any]:
    """Decode and verify an audit VC token. Raises ``jose.JWTError`` on failure."""
    return jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])


# ---------------------------------------------------------------------------
# Task-scoped VCs (5-minute TTL, bound to a specific transaction_id)
# ---------------------------------------------------------------------------

async def issue_task_scoped_vc(
    agent_id: str,
    transaction_id: str,
    operation: str,
    payload: dict[str, Any],
) -> str:
    """
    Issue a task-scoped VC valid **only** for a specific ``transaction_id``.

    The credential expires in TASK_VC_TTL_SECONDS (5 minutes). Agents MUST
    call ``validate_task_vc()`` before executing any database write.

    The ``jti`` (JWT ID) claim is set to ``transaction_id`` so validators can
    confirm the credential was issued for exactly the right transaction.

    Args:
        agent_id:       Agent performing the operation (e.g. "E").
        transaction_id: The UUID / reference of the transaction being processed.
        operation:      Machine-readable operation key.
        payload:        Contextual data — stored as a SHA-256 hash only.

    Returns:
        Signed JWT string (the task-scoped VC token).
    """
    card = get_card(agent_id)
    now = datetime.now(UTC)
    exp = now + timedelta(seconds=TASK_VC_TTL_SECONDS)

    claims: dict[str, Any] = {
        # Standard JWT claims
        "iss": card.issuer,
        "sub": agent_id,
        "jti": transaction_id,           # scope lock: JWT ID == transaction scope
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),     # 5-minute hard expiry
        # Finguard VC-specific claims
        "vc_type": "task_scoped",
        "agent_id": agent_id,
        "agent_name": card.name,
        "agent_version": card.version,
        "agent_did": card.did,
        "operation": operation,
        "transaction_id": transaction_id,
        "timestamp": now.isoformat(),
        "payload_hash": _payload_hash(payload),
    }

    token = jwt.encode(claims, settings.SECRET_KEY, algorithm="HS256")

    doc = {
        "vc_token": token,
        "claims": claims,
        "vc_type": "task_scoped",
        "transaction_id": transaction_id,
        "expires_at": exp.isoformat(),
        "created_at": now.isoformat(),
    }
    db = get_mongo_db()
    result = await db[COLLECTION].insert_one(doc)
    vc_doc_id = str(result.inserted_id)

    logger.info(
        "Task-scoped VC issued",
        agent_id=agent_id,
        agent_did=card.did,
        transaction_id=transaction_id,
        operation=operation,
        vc_doc_id=vc_doc_id,
        expires_at=exp.isoformat(),
    )
    return token


def validate_task_vc(
    token: str,
    transaction_id: str,
    agent_id: str,
) -> dict[str, Any]:
    """
    Validate a task-scoped VC before a database write.

    Enforces four properties:
    1. **Signature + expiry** — JWT decode raises ``JWTError`` on any failure.
    2. **Type check** — ``vc_type`` must equal ``"task_scoped"``.
    3. **Transaction scope** — ``jti`` must match ``transaction_id``.
    4. **Agent binding** — ``sub`` must match ``agent_id``.

    Args:
        token:          The task-scoped VC JWT string.
        transaction_id: Expected transaction ID this VC should be scoped to.
        agent_id:       Expected agent ID that issued the VC.

    Returns:
        Decoded and validated claims dict.

    Raises:
        jose.JWTError: if signature is invalid or token is expired.
        ValueError: if vc_type, jti, or sub claims don't match expectations.
    """
    claims = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])

    if claims.get("vc_type") != "task_scoped":
        raise ValueError(
            f"VC type mismatch: expected 'task_scoped', got {claims.get('vc_type')!r}"
        )

    if claims.get("jti") != transaction_id:
        raise ValueError(
            f"VC transaction scope mismatch: "
            f"expected {transaction_id!r}, got {claims.get('jti')!r}"
        )

    if claims.get("sub") != agent_id:
        raise ValueError(
            f"VC agent mismatch: expected {agent_id!r}, got {claims.get('sub')!r}"
        )

    return claims
