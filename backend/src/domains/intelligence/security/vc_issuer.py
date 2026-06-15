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

Signing (Ed25519, asymmetric)
-----------------------------
VCs are signed with the internal CA's **Ed25519** key (``key_manager.py``) — the
same trust root that signs agent cards — so the audit trail is *independently
verifiable* with the CA public key and is no longer forgeable by anyone holding
the symmetric application secret. Tokens use a compact ``header.payload.signature``
encoding (base64url JSON segments); the header records ``"alg": "EdDSA"``.

Backward compatibility
----------------------
VCs issued before this migration are JWTs signed with HS256 over ``SECRET_KEY``.
``_decode_vc`` inspects the token header and routes legacy ``HS256`` tokens
through ``jose`` + ``SECRET_KEY`` so existing ``trust_log`` entries still verify.
New tokens are always EdDSA.

Sprint 6 additions
-------------------
- ``issue_task_scoped_vc()`` — issues a VC with ``jti=transaction_id``, ``exp=now+5min``.
- ``validate_task_vc()``     — decodes, verifies, and enforces scope + agent binding.
- Audit VCs now embed ``agent_did`` from the signed AgentCard.
"""
from __future__ import annotations

import base64
import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any

from jose import JWTError, jwt

from src.core.config import settings
from src.core.logging import logger
from src.domains.intelligence.security.agent_cards import get_card
from src.domains.intelligence.security.key_manager import sign_data, verify_signature
from src.infrastructure.database.mongodb import get_mongo_db

COLLECTION = "trust_log"
VC_TTL_DAYS = 365
TASK_VC_TTL_SECONDS = 300  # 5-minute hard TTL for task-scoped VCs

# Compact-token header for EdDSA-signed VCs. The signature covers the exact
# ``<header_seg>.<payload_seg>`` ASCII string, so verification reconstructs the
# signing input from the received segments rather than re-serialising claims.
_VC_HEADER: dict[str, str] = {"alg": "EdDSA", "typ": "FG-VC"}


class VCError(Exception):
    """Raised when a Verifiable Credential fails to decode, verify, or expires."""


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(segment: str) -> bytes:
    padding = "=" * (-len(segment) % 4)
    return base64.urlsafe_b64decode(segment + padding)


def _encode_vc(claims: dict[str, Any]) -> str:
    """Serialise claims into an EdDSA-signed compact VC token."""
    header_seg = _b64url_encode(
        json.dumps(_VC_HEADER, sort_keys=True, separators=(",", ":")).encode()
    )
    payload_seg = _b64url_encode(
        json.dumps(claims, sort_keys=True, separators=(",", ":"), default=str).encode()
    )
    signing_input = f"{header_seg}.{payload_seg}".encode("ascii")
    signature = sign_data(signing_input)
    return f"{header_seg}.{payload_seg}.{_b64url_encode(signature)}"


def _enforce_exp(claims: dict[str, Any]) -> None:
    """Reject an expired VC (EdDSA path; jose enforces exp for legacy tokens)."""
    exp = claims.get("exp")
    if exp is None:
        return
    try:
        expired = int(exp) < int(datetime.now(UTC).timestamp())
    except (TypeError, ValueError) as exc:
        raise VCError(f"VC has a non-numeric exp claim: {exp!r}") from exc
    if expired:
        raise VCError("VC has expired")


def _decode_vc(token: str) -> dict[str, Any]:
    """Verify a VC token's signature + expiry and return its claims.

    EdDSA tokens are verified against the CA public key. Legacy HS256 tokens
    (``alg: HS256`` in the header) fall back to ``jose`` + ``SECRET_KEY``.

    Raises:
        VCError — malformed token, unsupported algorithm, bad signature, or
            expired credential.
    """
    parts = token.split(".")
    if len(parts) != 3:
        raise VCError("Malformed VC token (expected three segments)")
    header_seg, payload_seg, sig_seg = parts

    try:
        header = json.loads(_b64url_decode(header_seg))
    except (ValueError, json.JSONDecodeError) as exc:
        raise VCError("Malformed VC header") from exc

    alg = header.get("alg")
    if alg == "EdDSA":
        signing_input = f"{header_seg}.{payload_seg}".encode("ascii")
        try:
            signature = _b64url_decode(sig_seg)
        except ValueError as exc:
            raise VCError("Malformed VC signature") from exc
        if not verify_signature(signing_input, signature):
            raise VCError("VC signature verification failed")
        try:
            claims: dict[str, Any] = json.loads(_b64url_decode(payload_seg))
        except (ValueError, json.JSONDecodeError) as exc:
            raise VCError("Malformed VC payload") from exc
        _enforce_exp(claims)
        return claims

    if alg == "HS256":
        # Legacy VC issued before the Ed25519 migration — jose enforces both the
        # HMAC signature and the exp claim.
        try:
            return jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
        except JWTError as exc:
            raise VCError(f"Legacy HS256 VC verification failed: {exc}") from exc

    raise VCError(f"Unsupported VC algorithm: {alg!r}")


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
    token = _encode_vc(claims)

    doc = {
        "vc_token": token,
        "claims": claims,
        "vc_type": "audit",
        # Must be a native datetime (BSON Date), not an ISO string.
        # MongoDB TTL indexes only fire on BSON Date fields; string values
        # are silently ignored by the TTL background thread.
        "created_at": datetime.now(UTC),
    }

    db = get_mongo_db()
    result = await db[COLLECTION].insert_one(doc)
    return str(result.inserted_id)


def verify_vc(token: str) -> dict[str, Any]:
    """Decode and verify a VC token (EdDSA, or legacy HS256).

    Raises ``VCError`` on a malformed token, bad signature, or expiry.
    """
    return _decode_vc(token)


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

    token = _encode_vc(claims)

    doc = {
        "vc_token": token,
        "claims": claims,
        "vc_type": "task_scoped",
        "transaction_id": transaction_id,
        "expires_at": exp.isoformat(),
        # Native datetime so the TTL index (90-day retention) applies correctly.
        "created_at": now,
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


async def ensure_trust_log_ttl_index() -> None:
    """
    Create (or confirm) a 90-day TTL index on ``trust_log.created_at``.

    Safe to call on every application startup — MongoDB is idempotent for
    ``create_index`` calls when the index definition is unchanged.

    The index instructs MongoDB's TTL background thread to automatically
    delete documents where ``created_at`` is older than 7 776 000 seconds
    (90 days), preventing unbounded audit-log storage growth.

    IMPORTANT: ``created_at`` must be stored as a native BSON Date (Python
    ``datetime``), not an ISO string.  Both ``issue_vc`` and
    ``issue_task_scoped_vc`` have been updated to enforce this.
    """
    db = get_mongo_db()
    await db[COLLECTION].create_index(
        "created_at",
        expireAfterSeconds=7_776_000,   # 90 days
        name="trust_log_ttl_90d",
    )
    logger.info(
        "trust_log TTL index confirmed",
        collection=COLLECTION,
        expire_after_seconds=7_776_000,
    )


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
        VCError: if the signature is invalid or the token is expired.
        ValueError: if vc_type, jti, or sub claims don't match expectations.
    """
    claims = _decode_vc(token)

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
