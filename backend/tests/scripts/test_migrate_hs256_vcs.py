"""HS256→Ed25519 VC migration — pure re-sign helpers (hermetic, no MongoDB).

The DB walk is covered by integration tests; here we pin the security-critical
pure logic: an authentic HS256 VC is re-signed into a valid EdDSA VC with its
claims preserved, and a forged/invalid HS256 token is refused (never laundered
into an Ed25519 signature).
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from jose import jwt

from scripts.migrate_hs256_vcs import resign_hs256_token, token_alg
from src.core.config import settings
from src.domains.intelligence.security.vc_issuer import verify_vc


def _exp(seconds: int = 300) -> int:
    return int((datetime.now(UTC) + timedelta(seconds=seconds)).timestamp())


def test_token_alg_parses_header() -> None:
    hs = jwt.encode({"sub": "E", "exp": _exp()}, settings.SECRET_KEY, algorithm="HS256")
    assert token_alg(hs) == "HS256"
    assert token_alg("not-a-token") is None


def test_resign_preserves_claims_and_verifies_under_eddsa() -> None:
    claims = {"sub": "E", "vc_type": "audit", "operation": "x", "exp": _exp()}
    legacy = jwt.encode(claims, settings.SECRET_KEY, algorithm="HS256")

    new_token, decoded = resign_hs256_token(legacy, settings.SECRET_KEY)

    assert token_alg(new_token) == "EdDSA"
    # The re-signed token verifies under the asymmetric trust root...
    verified = verify_vc(new_token)
    # ...and carries exactly the original claims.
    assert verified == claims
    assert decoded["sub"] == "E"


def test_resign_refuses_forged_signature() -> None:
    forged = jwt.encode({"sub": "ADMIN", "exp": _exp()}, "attacker-secret", algorithm="HS256")
    with pytest.raises(ValueError, match="verification failed"):
        resign_hs256_token(forged, settings.SECRET_KEY)


def test_resign_refuses_non_hs256() -> None:
    from src.domains.intelligence.security.vc_issuer import _encode_vc

    eddsa = _encode_vc({"sub": "E", "exp": _exp()})
    with pytest.raises(ValueError, match="not HS256"):
        resign_hs256_token(eddsa, settings.SECRET_KEY)


def test_resign_preserves_expiry_of_expired_legacy_vc() -> None:
    # An authentic but already-expired audit VC is still re-signed (audit-trail
    # completeness), and the re-signed token stays expired.
    expired = jwt.encode({"sub": "E", "exp": _exp(-10)}, settings.SECRET_KEY, algorithm="HS256")
    new_token, _ = resign_hs256_token(expired, settings.SECRET_KEY)
    assert token_alg(new_token) == "EdDSA"
    from src.domains.intelligence.security.vc_issuer import VCError

    with pytest.raises(VCError, match="expired"):
        verify_vc(new_token)
