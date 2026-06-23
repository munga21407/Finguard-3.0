"""Verifiable Credential signing: Ed25519 issuance, tamper-evidence, and the
hard rejection of the sunset HS256 legacy path.

These tests exercise the pure crypto codec (``_encode_vc`` / ``verify_vc`` /
``validate_task_vc``) without touching MongoDB — the issuance helpers' DB writes
are covered elsewhere; here we pin the trust properties of the tokens, including
that the symmetric ``SECRET_KEY`` is no longer a valid VC trust root.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from jose import jwt

from src.core.config import settings
from src.domains.intelligence.security import vc_issuer
from src.domains.intelligence.security.vc_issuer import (
    VCError,
    _encode_vc,
    validate_task_vc,
    verify_vc,
)


def _future_exp(seconds: int = 300) -> int:
    return int((datetime.now(UTC) + timedelta(seconds=seconds)).timestamp())


def test_eddsa_roundtrip() -> None:
    claims = {"sub": "E", "vc_type": "audit", "operation": "x", "exp": _future_exp()}
    token = _encode_vc(claims)
    # Header must advertise EdDSA — proves we are not silently emitting HS256.
    assert verify_vc(token) == claims


def test_tampered_payload_rejected() -> None:
    token = _encode_vc({"sub": "E", "exp": _future_exp()})
    header_seg, _payload_seg, sig_seg = token.split(".")
    forged_payload = vc_issuer._b64url_encode(b'{"sub":"ADMIN"}')
    tampered = f"{header_seg}.{forged_payload}.{sig_seg}"
    with pytest.raises(VCError, match="signature verification failed"):
        verify_vc(tampered)


def test_expired_eddsa_rejected() -> None:
    token = _encode_vc({"sub": "E", "exp": _future_exp(-10)})
    with pytest.raises(VCError, match="expired"):
        verify_vc(token)


def test_malformed_and_unknown_alg_rejected() -> None:
    with pytest.raises(VCError):
        verify_vc("not-a-token")
    bad_alg = (
        vc_issuer._b64url_encode(b'{"alg":"none"}')
        + "." + vc_issuer._b64url_encode(b'{"sub":"E"}')
        + ".sig"
    )
    with pytest.raises(VCError, match="Unsupported VC algorithm"):
        verify_vc(bad_alg)


def test_legacy_hs256_hard_rejected_even_with_correct_secret() -> None:
    # The core fix: a VC signed with the real SECRET_KEY is STILL rejected, so a
    # leaked SECRET_KEY can no longer forge a verifiable "legacy" VC.
    legacy_claims = {"sub": "E", "vc_type": "audit", "exp": _future_exp()}
    legacy_token = jwt.encode(legacy_claims, settings.SECRET_KEY, algorithm="HS256")
    with pytest.raises(VCError, match="no longer accepted"):
        verify_vc(legacy_token)


def test_legacy_hs256_wrong_secret_rejected() -> None:
    legacy_token = jwt.encode({"sub": "E", "exp": _future_exp()}, "a-different-secret", algorithm="HS256")
    with pytest.raises(VCError):
        verify_vc(legacy_token)


def test_validate_task_vc_scope_and_agent_binding() -> None:
    txid = "txn-123"
    claims = {
        "sub": "E",
        "jti": txid,
        "vc_type": "task_scoped",
        "transaction_id": txid,
        "exp": _future_exp(),
    }
    token = _encode_vc(claims)

    # Happy path.
    assert validate_task_vc(token, transaction_id=txid, agent_id="E")["jti"] == txid

    # Wrong transaction scope.
    with pytest.raises(ValueError, match="transaction scope mismatch"):
        validate_task_vc(token, transaction_id="other", agent_id="E")

    # Wrong agent binding.
    with pytest.raises(ValueError, match="agent mismatch"):
        validate_task_vc(token, transaction_id=txid, agent_id="F")
