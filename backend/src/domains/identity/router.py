import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.core.security import decode_token
from src.domains.identity.dependencies import CurrentUser, RequireUserManage
from src.domains.identity.schemas import (
    LogoutRequest,
    RefreshRequest,
    TokenRequest,
    TokenResponse,
    UserCreate,
    UserResponse,
    UserUpdate,
)
from src.domains.identity.service import IdentityService
from src.infrastructure.cache.redis import get_auth_redis
from src.infrastructure.database.postgres import get_db

limiter = Limiter(key_func=get_remote_address, storage_uri=settings.RATE_LIMIT_REDIS_URL)
_bearer = HTTPBearer(auto_error=False)

router = APIRouter()

DBSession = Annotated[AsyncSession, Depends(get_db)]


@router.post("/register", response_model=UserResponse, status_code=201)
async def register(data: UserCreate, db: DBSession) -> UserResponse:
    user = await IdentityService(db).register(data)
    return UserResponse.model_validate(user)


@router.post("/token", response_model=TokenResponse)
@limiter.limit("5/minute")
async def login(request: Request, data: TokenRequest, db: DBSession) -> TokenResponse:
    return await IdentityService(db).login(data.email, data.password)


@router.post("/token/refresh", response_model=TokenResponse)
async def refresh(data: RefreshRequest, db: DBSession) -> TokenResponse:
    return await IdentityService(db).refresh(data.refresh_token)


@router.get("/me", response_model=UserResponse)
async def me(current_user: CurrentUser) -> UserResponse:
    """Return the authenticated user — the frontend hydrates session state from
    this rather than decoding (partial) claims out of the access token."""
    return UserResponse.model_validate(current_user)


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


@router.post("/logout", status_code=204)
async def logout(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    data: LogoutRequest | None = None,
) -> None:
    """
    Blacklist the access token's JTI (and, when supplied, the refresh token's
    JTI) in Redis (DB 1) so they are immediately rejected on subsequent
    requests.  Returns 204 regardless — missing or already-expired tokens are
    silently ignored so the client can always clear its local session.
    """
    if credentials is not None:
        await _blacklist_token(credentials.credentials, fallback_ttl=900)
    if data is not None and data.refresh_token:
        await _blacklist_token(
            data.refresh_token,
            fallback_ttl=settings.REFRESH_TOKEN_EXPIRE_DAYS * 86_400,
        )
