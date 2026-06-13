import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
from jose import JWTError, jwt

from src.core.config import settings
from src.core.exceptions import UnauthorizedError

# bcrypt has a hard 72-byte limit on the input; longer secrets must be truncated
# rather than raising.  We use the bcrypt library directly — passlib 1.7.4 is
# unmaintained and breaks against bcrypt >= 4.1 (it reads the removed
# ``bcrypt.__about__`` attribute).
_BCRYPT_MAX_BYTES = 72


def _to_bcrypt_bytes(plain: str) -> bytes:
    return plain.encode("utf-8")[:_BCRYPT_MAX_BYTES]


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(_to_bcrypt_bytes(plain), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(_to_bcrypt_bytes(plain), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        # Malformed/empty stored hash — treat as a non-match rather than raising.
        return False


def create_access_token(subject: str | int, extra: dict[str, Any] | None = None) -> str:
    payload: dict[str, Any] = {
        "sub": str(subject),
        "jti": str(uuid.uuid4()),   # unique ID — required for Redis blacklist revocation
        "exp": datetime.now(UTC) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
        "type": "access",
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_refresh_token(subject: str | int) -> str:
    payload: dict[str, Any] = {
        "sub": str(subject),
        "jti": str(uuid.uuid4()),   # unique ID — enables rotation + blacklist revocation
        "exp": datetime.now(UTC) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
        "type": "refresh",
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str) -> dict[str, Any]:
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except JWTError as exc:
        raise UnauthorizedError("Invalid or expired token") from exc
