"""
Verifiable Credential (VC) issuer for AI agent audit trails (Sprint 6).

Two credential types
---------------------
1. **Audit VCs** (``issue_vc``) — long-lived (365 days), written to ``trust_log``
   for SOC-2 / compliance requirements. Used by Agent E and ``ProposalService``
   to record every significant operation / human decision in a tamper-evident
   audit trail. This one is live and load-bearing.

2. **Task-scoped VCs** (``issue_task_scoped_vc`` / ``validate_task_vc``, wrapped
   as one unit by ``require_task_vc``) — short-lived (5 minutes), bound to a
   specific ``transaction_id``; designed to be issued and immediately
   validated, right before a write, by a caller proving it holds a fresh,
   in-scope credential for that exact transaction. Wired into
   ``reconciliation_service``'s Pass 1 (deterministic, in-process auto-apply)
   as of the "Task-scoped VC end-to-end" work — gated behind
   ``TASK_VC_ENFORCEMENT_ENABLED`` (off by default; shadow mode mints +
   validates + records metrics without blocking). This is a deliberate
   audit/defense-in-depth choice, not a claim that a real trust-domain split
   exists yet (it doesn't — one process, one trust boundary today; see
   ``AGENTS_REMEDIATION_SPRINTS.md``'s "Task-scoped VC end-to-end" section for
   the full reasoning and rollout plan).

   ``ProposalService`` gating a human-reviewed write is a **deliberate
   non-goal** for this credential type: a proposal can sit pending for hours
   to days awaiting a reviewer, which the 5-minute TTL cannot span.
   ``ProposalService`` instead pins a ``payload_hash`` (this module's
   ``payload_hash``) at proposal creation and re-checks it at approval — the
   right primitive for a *long-window integrity* guarantee, which is what
   that flow actually needs (see ``AGENTS_REMEDIATION_SPRINTS.md`` Sprint 8).
   Task-scoped VCs may still be minted at proposal *creation* time (a
   different claim — "this creation call was authorized," not "this payload
   is still fresh") without touching ``approve()``/``reject()`` at all.

Signing (Ed25519, asymmetric — EdDSA only)
------------------------------------------
VCs are signed with the internal CA's **Ed25519** key (``key_manager.py``) — the
same trust root that signs agent cards — so the audit trail is *independently
verifiable* with the CA public key and is **not** forgeable by anyone holding the
symmetric application secret. Tokens use a compact ``header.payload.signature``
encoding (base64url JSON segments); the header records ``"alg": "EdDSA"``.

HS256 sunset (legacy fallback removed)
--------------------------------------
Earlier VCs were JWTs signed with HS256 over the symmetric ``SECRET_KEY``.
Keeping that fallback in the verification path defeated the asymmetric upgrade:
anyone who learned ``SECRET_KEY`` could forge a "legacy" VC and poison the
``trust_log``. As of ``HS256_VC_SUNSET`` the fallback is **gone** — verification
is EdDSA-only and ``SECRET_KEY`` is never consulted here. Pre-sunset ``trust_log``
entries are re-signed with Ed25519 by the one-time ``scripts.migrate_hs256_vcs``
migration; any HS256 token presented after the sunset is hard-rejected.

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
from datetime import UTC, date, datetime, timedelta
from typing import Any

from pymongo.errors import OperationFailure

from src.core.config import settings
from src.core.logging import logger
from src.core.metrics import TASK_VC_ISSUED, TASK_VC_VALIDATE_FAIL
from src.domains.intelligence.security.agent_cards import get_card, verify_own_card
from src.domains.intelligence.security.key_manager import sign_data, verify_signature
from src.infrastructure.database.mongodb import get_mongo_db

COLLECTION = "trust_log"
VC_TTL_DAYS = 365
TASK_VC_TTL_SECONDS = 300  # 5-minute hard TTL for task-scoped VCs

# Hard cutoff after which legacy HS256-signed VCs are no longer accepted by the
# verifier. The symmetric ``SECRET_KEY`` fallback has been removed entirely;
# pre-sunset trust_log entries must be re-signed with Ed25519 via the one-time
# ``scripts.migrate_hs256_vcs`` migration before this date.
HS256_VC_SUNSET = date(2026, 6, 23)

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
    """Reject an expired VC by its ``exp`` claim (EdDSA verification path)."""
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

    Verification is **EdDSA-only**: tokens are checked against the CA public key.
    The legacy HS256 / ``SECRET_KEY`` fallback has been removed (see the
    ``HS256_VC_SUNSET`` note in the module docstring), so the symmetric secret is
    never a trust input here. HS256 tokens are hard-rejected.

    Raises:
        VCError — malformed token, unsupported/sunset algorithm, bad signature,
            or expired credential.
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
        # Symmetric-key VCs are no longer a trust root. Re-sign pre-sunset
        # trust_log entries with `python -m scripts.migrate_hs256_vcs`.
        raise VCError(
            "Legacy HS256 VCs are no longer accepted "
            f"(sunset {HS256_VC_SUNSET.isoformat()}); re-sign via "
            "scripts.migrate_hs256_vcs"
        )

    raise VCError(f"Unsupported VC algorithm: {alg!r}")


# ---------------------------------------------------------------------------
# Shared utilities
# ---------------------------------------------------------------------------

def payload_hash(payload: dict[str, Any]) -> str:
    """SHA-256 fingerprint of a JSON payload, key-sorted for determinism.

    Public (not ``_``-prefixed): also used by ``proposal_service`` to pin an
    ``AgentActionProposal``'s payload at creation time and detect tampering
    before it is replayed on approval — see ``ProposalService.approve``.
    """
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
        "payload_hash": payload_hash(payload),
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
    """Decode and verify a VC token (EdDSA only).

    Raises ``VCError`` on a malformed token, a sunset HS256 token, a bad
    signature, or expiry.
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

    The credential expires in TASK_VC_TTL_SECONDS (5 minutes) — meant to be
    issued and checked with ``validate_task_vc()`` immediately before a write,
    by a caller proving it holds a fresh, in-scope credential. See the module
    docstring for why nothing calls this today and what it's actually for.

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
        "payload_hash": payload_hash(payload),
    }

    token = _encode_vc(claims)

    doc = {
        "vc_token": token,
        "claims": claims,
        "vc_type": "task_scoped",
        "transaction_id": transaction_id,
        # The VC token's own 5-minute cryptographic expiry (informational only
        # — not what governs this document's lifetime in trust_log).
        "expires_at": exp.isoformat(),
        # Native datetime so the trust_log_ttl_90d index applies correctly.
        "created_at": now,
        # A second, longer-lived retention deadline distinct from the token's
        # own 5-minute exp — native BSON Date so trust_log_task_vc_retain_until
        # (see ensure_trust_log_ttl_index) can expire this document on its own
        # schedule (TASK_VC_RETENTION_DAYS) without touching audit VCs, which
        # never set this field.
        "retain_until": now + timedelta(days=settings.TASK_VC_RETENTION_DAYS),
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


async def _create_or_replace_index(
    coll: Any, keys: str, *, expire_after_seconds: int, name: str, partial_filter: dict[str, Any]
) -> None:
    """``create_index``, replacing an existing same-named index whose definition
    has drifted (MongoDB raises IndexOptionsConflict/IndexKeySpecsConflict
    rather than silently updating it — this makes ``ensure_trust_log_ttl_index``
    idempotent even across a definition change, e.g. adding the partial filter
    below to an index that predates it)."""
    try:
        await coll.create_index(
            keys,
            expireAfterSeconds=expire_after_seconds,
            name=name,
            partialFilterExpression=partial_filter,
        )
    except OperationFailure as exc:
        if exc.code not in (85, 86):  # IndexOptionsConflict, IndexKeySpecsConflict
            raise
        await coll.drop_index(name)
        await coll.create_index(
            keys,
            expireAfterSeconds=expire_after_seconds,
            name=name,
            partialFilterExpression=partial_filter,
        )


async def ensure_trust_log_ttl_index() -> None:
    """
    Create (or confirm) ``trust_log``'s two TTL indexes — audit VCs (90 days)
    and task-scoped VCs (``TASK_VC_RETENTION_DAYS``, 365 by default) — on their
    own independent schedules.

    Safe to call on every application startup.

    Audit VCs (``issue_vc``) and task-scoped VCs (``issue_task_scoped_vc``)
    share one collection but need different retention: without the partial
    filters below, the 90-day ``created_at`` index (which every document sets)
    would delete a task-scoped document before its own longer-lived
    ``retain_until`` index ever got a chance to — TTL indexes are independent
    background sweeps, not a priority-ordered chain, so whichever condition a
    document meets first wins. Filtered on ``vc_type`` (an equality match —
    MongoDB partial-index filters don't support ``$exists: false``, only a
    narrow operator set including ``$eq``, which every document's ``vc_type``
    already satisfies).

    IMPORTANT: both ``created_at`` and ``retain_until`` must be stored as
    native BSON Dates (Python ``datetime``), not ISO strings — MongoDB's TTL
    background thread silently ignores string-valued fields.
    """
    coll = get_mongo_db()[COLLECTION]
    await _create_or_replace_index(
        coll, "created_at",
        expire_after_seconds=7_776_000,   # 90 days
        name="trust_log_ttl_90d",
        partial_filter={"vc_type": "audit"},
    )
    await _create_or_replace_index(
        coll, "retain_until",
        expire_after_seconds=0,   # expire exactly at the stored timestamp
        name="trust_log_task_vc_retain_until",
        partial_filter={"vc_type": "task_scoped"},
    )
    logger.info(
        "trust_log TTL indexes confirmed",
        collection=COLLECTION,
        audit_expire_after_seconds=7_776_000,
        task_vc_retention_days=settings.TASK_VC_RETENTION_DAYS,
    )


def validate_task_vc(
    token: str,
    transaction_id: str,
    agent_id: str,
) -> dict[str, Any]:
    """
    Validate a task-scoped VC before a database write.

    Enforces four properties:
    1. **Signature + expiry** — EdDSA decode raises ``VCError`` on any failure.
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


async def require_task_vc(
    *, agent_id: str, transaction_id: str, operation: str, payload: dict[str, Any]
) -> None:
    """
    Mint and immediately validate a task-scoped VC for one write — audit /
    defense-in-depth on a live, in-process write path (single trust boundary
    today; see the module docstring and ``core.config.TASK_VC_ENFORCEMENT_ENABLED``).

    **Shadow mode** (default, ``TASK_VC_ENFORCEMENT_ENABLED=False``): always
    mints, validates, and records the ``agent_task_vc_*`` metrics, but never
    raises on failure — only logs a warning — so the write proceeds unblocked
    while the rollout is observed.

    **Enforce mode** (``TASK_VC_ENFORCEMENT_ENABLED=True``): re-raises the
    underlying failure (own-card verification, mint error, or
    ``VCError``/``ValueError`` from ``validate_task_vc``) so the caller can
    react per its own fail-closed policy — e.g. skip just this one item
    rather than aborting an entire batch (see ``reconciliation_service``'s
    per-match loop).

    Deliberately one function, not separable mint/validate calls: a caller
    that mints for one id and validates against another by mistake is a real
    (if unlikely) mistake this shape rules out structurally. Also verifies
    ``agent_id``'s own signed card (``agent_cards.verify_own_card``) first —
    every task-VC-gated write site gets that check without calling it
    separately.
    """
    try:
        verify_own_card(agent_id)
        token = await issue_task_scoped_vc(agent_id, transaction_id, operation, payload)
        validate_task_vc(token, transaction_id=transaction_id, agent_id=agent_id)
    except Exception as exc:
        TASK_VC_VALIDATE_FAIL.labels(
            agent_id=agent_id, operation=operation, reason=type(exc).__name__
        ).inc()
        logger.warning(
            "Task-scoped VC check failed",
            agent_id=agent_id,
            operation=operation,
            transaction_id=transaction_id,
            error=str(exc),
        )
        if settings.TASK_VC_ENFORCEMENT_ENABLED:
            raise
        return

    TASK_VC_ISSUED.labels(agent_id=agent_id, operation=operation).inc()
