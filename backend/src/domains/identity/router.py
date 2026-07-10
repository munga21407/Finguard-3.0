import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.core.csrf import CSRF_COOKIE_NAME, generate_csrf_token, require_csrf_token
from src.core.exceptions import UnauthorizedError
from src.core.security import ACCESS_COOKIE_NAME, SESSION_COOKIE_NAME, decode_token
from src.domains.audit.models import AuditAction, AuditActorType, AuditOutcome
from src.domains.audit.service import AuditService
from src.domains.identity.dependencies import CurrentUser, RequireUserManage
from src.domains.identity.schemas import (
    AccessTokenResponse,
    ForgotPasswordRequest,
    ResendVerificationRequest,
    ResetPasswordRequest,
    TokenRequest,
    UserCreate,
    UserResponse,
    UserUpdate,
    VerifyEmailRequest,
)
from src.domains.identity.service import IdentityService
from src.infrastructure.cache.redis import get_auth_redis
from src.infrastructure.database.postgres import get_db

limiter = Limiter(key_func=get_remote_address, storage_uri=settings.RATE_LIMIT_REDIS_URL)
_bearer = HTTPBearer(auto_error=False)


def _client_ip(request: Request) -> str:
    """Best-effort source IP for per-client login lockout.

    Behind the nginx reverse proxy ``request.client.host`` is the proxy's IP
    (identical for every user), so the per-IP lockout would collapse back to a
    per-email one.  Prefer the left-most ``X-Forwarded-For`` entry (the original
    client as recorded by the trusted proxy) when present.  Operators must ensure
    nginx sets X-Forwarded-For and does not forward a client-supplied value
    verbatim; absent a proxy the direct peer address is used.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        first = forwarded.split(",")[0].strip()
        if first:
            return first
    return request.client.host if request.client else "unknown"

router = APIRouter()

DBSession = Annotated[AsyncSession, Depends(get_db)]

# ── Cookie configuration ───────────────────────────────────────────────────────
_REFRESH_COOKIE = "fg_refresh_token"
_REFRESH_COOKIE_PATH = "/api/v1/identity"   # only sent to auth endpoints
_COOKIE_MAX_AGE = settings.REFRESH_TOKEN_EXPIRE_DAYS * 86_400
_ACCESS_COOKIE_MAX_AGE = settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
# secure=True requires HTTPS — safe to enable only in production.
# Never set secure=True behind HTTP in development or tests; the browser
# silently drops the cookie.
_COOKIE_SECURE = settings.ENVIRONMENT == "production"


def _set_auth_cookies(
    response: Response, access_token: str, refresh_token: str, csrf_token: str
) -> None:
    """Set the access (HttpOnly), refresh (HttpOnly), CSRF, and session cookies."""
    # Access token — HttpOnly so JS can't read it (XSS-exfiltration safe), sent
    # to every API path. SameSite=strict; the double-submit CSRF token guards
    # cross-site mutations.
    response.set_cookie(
        key=ACCESS_COOKIE_NAME,
        value=access_token,
        httponly=True,
        secure=_COOKIE_SECURE,
        samesite="strict",
        path="/",
        max_age=_ACCESS_COOKIE_MAX_AGE,
    )
    response.set_cookie(
        key=_REFRESH_COOKIE,
        value=refresh_token,
        httponly=True,
        secure=_COOKIE_SECURE,
        samesite="strict",
        path=_REFRESH_COOKIE_PATH,
        max_age=_COOKIE_MAX_AGE,
    )
    # The CSRF cookie is intentionally NOT HttpOnly — the frontend reads it and
    # echoes it back as the X-CSRF-Token header (double-submit pattern).
    response.set_cookie(
        key=CSRF_COOKIE_NAME,
        value=csrf_token,
        httponly=False,
        secure=_COOKIE_SECURE,
        samesite="strict",
        path="/",
        max_age=_COOKIE_MAX_AGE,
    )
    # Non-HttpOnly presence marker for the Next.js Edge middleware (which cannot
    # read the HttpOnly access cookie). SameSite=lax so top-level navigations
    # still see it. Carries no token material — just "a session exists".
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value="1",
        httponly=False,
        secure=_COOKIE_SECURE,
        samesite="lax",
        path="/",
        max_age=_COOKIE_MAX_AGE,
    )


def _clear_auth_cookies(response: Response) -> None:
    """Expire every auth cookie (forces the browser to delete them on receipt)."""
    response.delete_cookie(
        key=ACCESS_COOKIE_NAME,
        path="/",
        samesite="strict",
        secure=_COOKIE_SECURE,
    )
    response.delete_cookie(
        key=_REFRESH_COOKIE,
        path=_REFRESH_COOKIE_PATH,
        samesite="strict",
        secure=_COOKIE_SECURE,
    )
    response.delete_cookie(
        key=CSRF_COOKIE_NAME,
        path="/",
        samesite="strict",
        secure=_COOKIE_SECURE,
    )
    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        path="/",
        samesite="lax",
        secure=_COOKIE_SECURE,
    )


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/register", response_model=UserResponse, status_code=201)
async def register(data: UserCreate, db: DBSession) -> UserResponse:
    user = await IdentityService(db).register(data)
    return UserResponse.model_validate(user)


@router.post("/token", response_model=AccessTokenResponse)
@limiter.limit("5/minute")
async def login(
    request: Request,
    response: Response,
    data: TokenRequest,
    db: DBSession,
) -> AccessTokenResponse:
    """Authenticate and issue tokens.

    The access token is set as an HttpOnly, SameSite=Strict cookie (invisible to
    JS, safe from XSS exfiltration) and also returned in the JSON body for
    non-browser clients. The refresh token is likewise an HttpOnly cookie. A
    non-HttpOnly CSRF cookie is set for the double-submit pattern that guards all
    cookie-authenticated mutations.
    """
    try:
        result = await IdentityService(db).login(
            data.email, data.password, ip=_client_ip(request)
        )
    except Exception as exc:  # noqa: BLE001 — audit then re-raise; handler unchanged
        # Audit the failed attempt (bad credentials, disabled/unverified account,
        # lockout) before propagating. actor_id is unknown — the attempted email
        # is recorded as the label so brute-force / probing is still attributable.
        await AuditService(db).record_safe(
            action=AuditAction.AUTH_LOGIN_FAILED,
            actor_type=AuditActorType.USER,
            actor_label=data.email,
            resource_type="session",
            outcome=AuditOutcome.FAILURE,
            metadata={"reason": type(exc).__name__},
        )
        raise
    _set_auth_cookies(
        response, result.access_token, result.refresh_token, generate_csrf_token()
    )
    await AuditService(db).record_safe(
        action=AuditAction.AUTH_LOGIN,
        actor_type=AuditActorType.USER,
        actor_label=data.email,
        resource_type="session",
        outcome=AuditOutcome.SUCCESS,
    )
    return AccessTokenResponse(access_token=result.access_token)


@router.post("/verify-email", status_code=204)
@limiter.limit("10/minute")
async def verify_email(
    request: Request, data: VerifyEmailRequest, db: DBSession
) -> Response:
    """Confirm email ownership from the link's token. Idempotent."""
    await IdentityService(db).verify_email(data.token)
    return Response(status_code=204)


@router.post("/resend-verification", status_code=202)
@limiter.limit("5/minute")
async def resend_verification(
    request: Request, data: ResendVerificationRequest, db: DBSession
) -> dict[str, str]:
    """Re-send the verification email. Always 202 (no account enumeration)."""
    await IdentityService(db).resend_verification(data.email)
    return {"detail": "If that account needs verification, a new link is on its way."}


@router.post("/forgot-password", status_code=202)
@limiter.limit("5/minute")
async def forgot_password(
    request: Request, data: ForgotPasswordRequest, db: DBSession
) -> dict[str, str]:
    """Request a password-reset link.

    Always returns 202 with the same body whether or not the email is registered,
    so this endpoint can't be used to enumerate accounts. Rate-limited per IP to
    stop it being used to flood a victim's inbox.
    """
    await IdentityService(db).request_password_reset(data.email)
    return {"detail": "If that email is registered, a reset link is on its way."}


@router.post("/reset-password", status_code=204)
@limiter.limit("5/minute")
async def reset_password(
    request: Request, data: ResetPasswordRequest, db: DBSession
) -> Response:
    """Set a new password from a valid reset token; ends all existing sessions."""
    await IdentityService(db).reset_password(data.token, data.new_password)
    return Response(status_code=204)


@router.post("/token/refresh", response_model=AccessTokenResponse)
async def refresh(
    request: Request,
    response: Response,
    db: DBSession,
    _csrf: Annotated[None, Depends(require_csrf_token)],
) -> AccessTokenResponse:
    """Rotate the refresh token.

    Reads the refresh token from the HttpOnly ``fg_refresh_token`` cookie (sent
    automatically by the browser).  Validates the double-submit CSRF token.
    On success: issues a new access token (body) and rotates the refresh cookie.
    On replay detection: revokes the entire token family before rejecting.
    """
    refresh_cookie = request.cookies.get(_REFRESH_COOKIE)
    if not refresh_cookie:
        raise UnauthorizedError("No refresh token cookie present")
    result = await IdentityService(db).refresh(refresh_cookie)
    _set_auth_cookies(
        response, result.access_token, result.refresh_token, generate_csrf_token()
    )
    return AccessTokenResponse(access_token=result.access_token)


@router.get("/me", response_model=UserResponse)
async def me(current_user: CurrentUser) -> UserResponse:
    """Return the authenticated user — the frontend hydrates session state from
    this rather than decoding (partial) claims out of the access token."""
    return UserResponse.model_validate(current_user)


@router.post("/logout", status_code=204)
async def logout(
    request: Request,
    response: Response,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> None:
    """Revoke the current session.

    Blacklists the access token's JTI (via Authorization header) and the
    refresh token's JTI (via cookie) in Redis so neither can be reused.
    Always returns 204 — missing or already-expired tokens are silently ignored
    so the client can always clear its local session.
    Clears both auth cookies so the browser drops them immediately.
    """
    # Blacklist the access token from whichever transport carried it — the
    # HttpOnly cookie (browser) or the Authorization header (API client).
    access_token = request.cookies.get(ACCESS_COOKIE_NAME) or (
        credentials.credentials if credentials is not None else None
    )
    if access_token is not None:
        await _blacklist_token(access_token, fallback_ttl=900)
    refresh_cookie = request.cookies.get(_REFRESH_COOKIE)
    if refresh_cookie:
        await _blacklist_token(
            refresh_cookie,
            fallback_ttl=settings.REFRESH_TOKEN_EXPIRE_DAYS * 86_400,
        )
    _clear_auth_cookies(response)


# ── User administration (requires user:manage) ─────────────────────────────────

@router.get("/users", response_model=list[UserResponse])
async def list_users(
    db: DBSession,
    _: RequireUserManage,
    limit: int = Query(default=100, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[UserResponse]:
    users = await IdentityService(db).list_users(limit=limit, offset=offset)
    return [UserResponse.model_validate(u) for u in users]


@router.patch("/users/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: uuid.UUID,
    data: UserUpdate,
    db: DBSession,
    _: RequireUserManage,
) -> UserResponse:
    """Verify a user, change their role, or (de)activate them. Admin-only."""
    user = await IdentityService(db).update_user(user_id, data)
    return UserResponse.model_validate(user)


# ── Internal helper ────────────────────────────────────────────────────────────

async def _blacklist_token(token: str, fallback_ttl: int) -> None:
    """Blacklist a JWT's jti until its natural expiry. Best-effort / never raises."""
    try:
        payload = decode_token(token)
    except Exception:
        return
    jti: str | None = payload.get("jti")
    if jti is None:
        return
    exp: int | None = payload.get("exp")
    now_ts = int(datetime.now(UTC).timestamp())
    ttl = max(1, exp - now_ts) if exp else fallback_ttl
    await get_auth_redis().setex(f"blacklist:{jti}", ttl, "1")
