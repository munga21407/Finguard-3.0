"""
Internal Certificate Authority key manager (Sprint 6).

The Finguard internal CA uses Ed25519 (RFC 8032) to sign agent identity cards
and verify them before state passes between agents. Ed25519 was chosen because:
  - 64-byte signatures (compact for JWT sub-claim storage)
  - Deterministic — no side-channel leakage from nonce reuse
  - ~100k sign/verify ops per second on commodity hardware

Key loading priority
---------------------
1. ``FINGUARD_CA_PRIVATE_KEY_HEX`` env var — 32 raw bytes, hex-encoded (64 chars).
   Set this in production using your secrets manager (e.g. AWS Secrets Manager,
   HashiCorp Vault, or Kubernetes Secrets mounted as env vars).

2. Fixed dev-only seed (development / test fallback). When no explicit key is
   provided outside production, the CA key is derived from a constant domain
   string — **never** from the application auth secret (``SECRET_KEY``). This
   keeps the CA trust root fully decoupled from authentication: rotating one
   never silently changes the other. Production refuses to boot without an
   explicit key (same fail-in-prod / warn-in-dev contract as the read-only DB
   engine and schema-migration guards).

NEVER commit a real FINGUARD_CA_PRIVATE_KEY_HEX value to version control.
Generate one with:  python -c "import secrets; print(secrets.token_hex(32))"
"""
from __future__ import annotations

import hashlib
from functools import lru_cache

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from src.core.config import settings

# Fixed, public dev-only derivation domain. Produces a stable key across local
# restarts WITHOUT coupling to SECRET_KEY and without embedding usable
# production key material in source. Only ever used outside production.
_DEV_KEY_DOMAIN = b"finguard-ca-ed25519:dev-only-fixed-seed:v1"


@lru_cache(maxsize=1)
def _load_ca_private_key() -> Ed25519PrivateKey:
    """Load or derive the CA private key (cached for the process lifetime)."""
    raw_hex = settings.FINGUARD_CA_PRIVATE_KEY_HEX.strip()
    if raw_hex:
        raw_bytes = bytes.fromhex(raw_hex)
        if len(raw_bytes) != 32:
            raise ValueError(
                "FINGUARD_CA_PRIVATE_KEY_HEX must be exactly 32 bytes (64 hex chars). "
                f"Got {len(raw_bytes)} bytes."
            )
        return Ed25519PrivateKey.from_private_bytes(raw_bytes)

    if settings.ENVIRONMENT == "production":
        raise RuntimeError(
            "FINGUARD_CA_PRIVATE_KEY_HEX must be set in production. The Ed25519 "
            "internal CA signs agent cards and Verifiable Credentials; it must "
            "never be derived implicitly. Generate one with "
            "`python -c \"import secrets; print(secrets.token_hex(32))\"` and "
            "inject it via your secrets manager."
        )

    # Dev/test only: deterministic key from a fixed domain string — stable across
    # restarts, and decoupled from the auth secret.
    seed = hashlib.sha256(_DEV_KEY_DOMAIN).digest()
    return Ed25519PrivateKey.from_private_bytes(seed)


def get_ca_public_key_bytes() -> bytes:
    """Return the CA Ed25519 public key as 32 raw bytes (for out-of-band verification)."""
    pub: Ed25519PublicKey = _load_ca_private_key().public_key()
    return pub.public_bytes(Encoding.Raw, PublicFormat.Raw)


def get_ca_public_key_hex() -> str:
    """Return the CA Ed25519 public key as a hex string (useful for logging/config)."""
    return get_ca_public_key_bytes().hex()


def sign_data(data: bytes) -> bytes:
    """
    Sign arbitrary bytes with the CA private key.

    Returns a deterministic 64-byte Ed25519 signature.
    """
    return _load_ca_private_key().sign(data)


def verify_signature(data: bytes, signature: bytes) -> bool:
    """
    Verify a 64-byte Ed25519 signature against the CA public key.

    Returns True if the signature is valid, False otherwise (never raises).
    """
    if len(signature) != 64:
        return False
    try:
        pub: Ed25519PublicKey = _load_ca_private_key().public_key()
        pub.verify(signature, data)
        return True
    except Exception:
        return False
