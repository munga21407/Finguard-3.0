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
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from src.core.config import settings

CSRF_COOKIE_NAME = "fg_csrf"
_CSRF_HEADER = "x-csrf-token"  # HTTP headers are case-insensitive; use lowercase

# Methods that never mutate state — exempt from CSRF by definition.
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})

# Mutating paths that must NOT require a CSRF token.  Keep this list tiny and
# justify every entry — each is a hole in the default-deny posture:
#   - /mpesa/callback : inbound Daraja webhook; server-to-server, authenticated
#                       by Safaricom signature, carries no cookie/CSRF token.
#   - /token          : login; no session exists yet and this is what SETS the
#                       CSRF cookie in the first place.
#   - /register       : public account creation; no authenticated session.
CSRF_EXEMPT_PATHS = frozenset(
    {
        "/api/v1/finance/mpesa/callback",
        "/api/v1/identity/token",
        "/api/v1/identity/register",
    }
)


def generate_csrf_token() -> str:
    """Return a 64-char hex random token suitable for the double-submit cookie."""
    return secrets.token_hex(32)


def _validate_tokens(cookie_val: str | None, header_val: str | None) -> str | None:
    """Pure double-submit check; return an error message or None if OK."""
    if not cookie_val or not header_val:
        return "CSRF validation failed: missing token"
    if not hmac.compare_digest(cookie_val, header_val):
        return "CSRF validation failed: token mismatch"
    return None


def _csrf_error(request: Request) -> str | None:
    """Validate the double-submit token on a request; error message or None."""
    return _validate_tokens(
        request.cookies.get(CSRF_COOKIE_NAME), request.headers.get(_CSRF_HEADER)
    )


def _csrf_required(method: str, path: str) -> bool:
    """Whether CSRF must be enforced for this method/path under current settings."""
    return (
        settings.CSRF_ENABLED
        and method not in _SAFE_METHODS
        and path not in CSRF_EXEMPT_PATHS
    )


async def require_csrf_token(request: Request) -> None:
    """FastAPI dependency — raises 403 when the CSRF token is absent or mismatched.

    Retained on /token/refresh so that endpoint is protected independently of the
    global middleware (defence in depth, and unaffected by the CSRF_ENABLED flag).
    """
    error = _csrf_error(request)
    if error is not None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=error)


class CSRFMiddleware(BaseHTTPMiddleware):
    """Enforce double-submit CSRF on every cookie-authenticated mutating request.

    Because the access token is now an auto-sent HttpOnly cookie, every unsafe
    method is CSRF-eligible — so we default-deny across the board rather than
    annotate each route (which is easy to forget on a new endpoint).  Safe
    methods and the small ``CSRF_EXEMPT_PATHS`` allowlist pass through.  Gated by
    ``settings.CSRF_ENABLED`` so the test suite (which authenticates via a
    dependency override and sends no token) can disable it.
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        if _csrf_required(request.method, request.url.path):
            error = _csrf_error(request)
            if error is not None:
                return JSONResponse(
                    status_code=status.HTTP_403_FORBIDDEN,
                    content={"detail": error},
                )
        return await call_next(request)
