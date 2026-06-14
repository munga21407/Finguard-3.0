"""CSRF protection via the double-submit cookie pattern.

Flow:
  1. On login the server sets a non-HttpOnly ``fg_csrf`` cookie containing a
     random 64-hex-char token.  JavaScript can read this cookie.
  2. On every call to /token/refresh the client includes the cookie value as
     the ``X-CSRF-Token`` request header.
  3. ``require_csrf_token`` validates that header == cookie using a
     constant-time comparison — a cross-origin attacker cannot read the cookie
     (same-origin restriction) so they cannot forge the header.

SameSite=strict is also set on both auth cookies, providing independent
protection.  CSRF adds a second layer so a SameSite misconfiguration or
sub-domain compromise does not immediately collapse the session security model.
"""

import hmac
import secrets

from fastapi import HTTPException, Request, status

CSRF_COOKIE_NAME = "fg_csrf"
_CSRF_HEADER = "x-csrf-token"  # HTTP headers are case-insensitive; use lowercase


def generate_csrf_token() -> str:
    """Return a 64-char hex random token suitable for the double-submit cookie."""
    return secrets.token_hex(32)


async def require_csrf_token(request: Request) -> None:
    """FastAPI dependency — raises 403 when the CSRF token is absent or mismatched.

    Dependency is applied only to the endpoints that read the HttpOnly refresh
    cookie (/token/refresh), where CSRF would be exploitable.  Endpoints
    authenticated purely via Bearer token are inherently CSRF-safe and do not
    need this dependency.
    """
    cookie_val: str | None = request.cookies.get(CSRF_COOKIE_NAME)
    header_val: str | None = request.headers.get(_CSRF_HEADER)

    if not cookie_val or not header_val:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CSRF validation failed: missing token",
        )

    if not hmac.compare_digest(cookie_val, header_val):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CSRF validation failed: token mismatch",
        )
