import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
from jose import JWTError, jwt

from src.core.config import settings
from src.core.exceptions import UnauthorizedError

# Auth cookie names. The access token is delivered as an HttpOnly cookie so it
# is invisible to JS (XSS-exfiltration safe); ``fg_session`` is a non-HttpOnly
# presence marker the Next.js Edge middleware reads to gate /dashboard routes.
ACCESS_COOKIE_NAME = "fg_access_token"
SESSION_COOKIE_NAME = "fg_session"

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
        "iat": datetime.now(UTC),   # issued-at — password reset invalidates older tokens
        "exp": datetime.now(UTC) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
        "type": "access",
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_refresh_token(subject: str | int, family_id: str | None = None) -> str:
    """Create a signed refresh token.

    ``family_id`` links every token in a rotation chain so that replaying a
    consumed token (theft indicator) can invalidate the entire chain.  When not
    supplied a fresh UUID is generated — this happens on the initial login.
    Subsequent refresh rotations pass the existing ``family_id`` forward.
    """
    payload: dict[str, Any] = {
        "sub": str(subject),
        "jti": str(uuid.uuid4()),       # unique per rotation — drives the blacklist
        "family_id": family_id or str(uuid.uuid4()),  # shared across the chain
        "iat": datetime.now(UTC),       # issued-at — password reset invalidates older tokens
        "exp": datetime.now(UTC) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
        "type": "refresh",
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str) -> dict[str, Any]:
    try:
        return jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except JWTError as exc:
        raise UnauthorizedError("Invalid or expired token") from exc


def token_issued_after_password_change(
    iat: int | None, password_changed_at: datetime | None
) -> bool:
    """Whether a token is still valid relative to the user's last password reset.

    A token minted (``iat``) before the reset is dead. Legacy tokens without an
    ``iat`` claim, or users who have never reset (``password_changed_at`` is None),
    are unaffected — return True.
    """
    if iat is None or password_changed_at is None:
        return True
    return datetime.fromtimestamp(iat, tz=UTC) >= password_changed_at


def create_password_reset_token(user_id: str) -> str:
    """Short-lived, single-purpose token embedded in the reset email link."""
    payload = {
        "sub": str(user_id),
        "type": "password_reset",
        "jti": str(uuid.uuid4()),
        "exp": datetime.now(UTC)
        + timedelta(minutes=settings.PASSWORD_RESET_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_password_reset_token(token: str) -> dict[str, Any]:
    """Return the claims of a valid, unexpired reset token, else raise.

    Includes ``sub`` (user id), ``jti`` (for one-time-use blacklisting), and
    ``exp`` so the caller can set a matching blacklist TTL.
    """
    try:
        payload = jwt.decode(
            token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
        )
    except JWTError as exc:
        raise UnauthorizedError("Invalid or expired reset link") from exc
    if payload.get("type") != "password_reset":
        raise UnauthorizedError("Invalid or expired reset link")
    return payload


def create_email_verification_token(user_id: str) -> str:
    """Token embedded in the account-verification email link."""
    payload = {
        "sub": str(user_id),
        "type": "email_verify",
        "jti": str(uuid.uuid4()),
        "exp": datetime.now(UTC)
        + timedelta(hours=settings.EMAIL_VERIFICATION_EXPIRE_HOURS),
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_email_verification_token(token: str) -> str:
    """Return the user id from a valid, unexpired verification token, else raise."""
    try:
        payload = jwt.decode(
            token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
        )
    except JWTError as exc:
        raise UnauthorizedError("Invalid or expired verification link") from exc
    if payload.get("type") != "email_verify":
        raise UnauthorizedError("Invalid or expired verification link")
    return str(payload["sub"])


def create_unsubscribe_token(email: str, category: str) -> str:
    """Sign a stable, non-expiring one-click unsubscribe token.

    Unsubscribe links must keep working indefinitely (they live in old emails), so
    there is no ``exp``. The ``type`` claim prevents an unsubscribe token from
    being replayed as an auth token and vice-versa.
    """
    payload = {"email": email.lower(), "cat": category, "type": "unsubscribe"}
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_unsubscribe_token(token: str) -> tuple[str, str]:
    """Return ``(email, category)`` from a valid unsubscribe token, else raise."""
    try:
        payload = jwt.decode(
            token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
        )
    except JWTError as exc:
        raise UnauthorizedError("Invalid unsubscribe link") from exc
    if payload.get("type") != "unsubscribe":
        raise UnauthorizedError("Invalid unsubscribe link")
    return str(payload["email"]), str(payload["cat"])
