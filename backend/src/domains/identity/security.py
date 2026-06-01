"""
Identity domain security facade.

Re-exports JWT and bcrypt helpers from src.core.security so that
the identity domain is self-contained per the module structure spec
and other domains never need to import from core.security directly.
"""
from src.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)

__all__ = [
    "create_access_token",
    "create_refresh_token",
    "decode_token",
    "hash_password",
    "verify_password",
]
