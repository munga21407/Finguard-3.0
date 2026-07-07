"""
FastAPI dependency factories for the identity domain.

Provides `get_current_user` and the `CurrentUser` annotated type so
that other domains can protect routes without importing from core.security
directly.
"""
from __future__ import annotations

import uuid
from collections.abc import Callable, Coroutine
from typing import Annotated, Any

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import ForbiddenError, UnauthorizedError
from src.core.security import ACCESS_COOKIE_NAME, decode_token
from src.domains.identity.models import User
from src.domains.identity.permissions import Permission, has_permission
from src.domains.identity.repository import UserRepository
from src.infrastructure.cache.redis import get_auth_redis
from src.infrastructure.database.postgres import get_db

_bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    # Prefer the HttpOnly access cookie (browser sessions); fall back to the
    # Authorization: Bearer header for programmatic / non-browser clients.
    token = request.cookies.get(ACCESS_COOKIE_NAME) or (
        credentials.credentials if credentials else None
    )
    if not token:
        raise UnauthorizedError("Missing authentication credentials")
    payload = decode_token(token)

    # Reject token-type confusion: only access tokens authenticate a request.
    # Access and refresh tokens are signed with the same key, so without this
    # check a (longer-lived, broader) refresh token presented in the access
    # cookie or Authorization header would authenticate. Tokens minted before
    # the ``type`` claim existed have no type and are allowed through — they
    # expire naturally via their ``exp`` claim.
    token_type: str | None = payload.get("type")
    if token_type is not None and token_type != "access":
        raise UnauthorizedError("Invalid token type")

    raw_id: str | None = payload.get("sub")
    if not raw_id:
        raise UnauthorizedError("Invalid token payload")

    # Reject tokens whose JTI has been added to the Redis blacklist (e.g. on logout).
    # Tokens issued before the jti claim was introduced have no jti and bypass this
    # check — they expire naturally via their exp claim.
    jti: str | None = payload.get("jti")
    if jti is not None and await get_auth_redis().exists(f"blacklist:{jti}"):
        raise UnauthorizedError("Token has been revoked")

    user = await UserRepository(db).get_by_id(uuid.UUID(raw_id))
    if not user or not user.is_active:
        raise UnauthorizedError("User not found or inactive")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_permission(
    *required: Permission,
) -> Callable[[User], Coroutine[Any, Any, User]]:
    """
    Build a dependency that authorizes the current user against *required*
    permissions (all must be granted by the user's role) and returns the user.

    Default-deny: if the user's role does not grant every requested permission a
    403 is raised.  Authentication (a valid, non-revoked token for an active
    user) is still enforced first via ``get_current_user``.

    Usage::

        @router.post("/ledger")
        async def post_ledger_entry(
            data: LedgerEntryCreate,
            db: DBSession,
            user: Annotated[User, Depends(require_permission(Permission.FINANCE_WRITE))],
        ): ...
    """

    async def _dependency(user: CurrentUser) -> User:
        missing = [p for p in required if not has_permission(user.role, p)]
        if missing:
            raise ForbiddenError(
                "Insufficient permissions: "
                + ", ".join(sorted(p.value for p in missing))
            )
        return user

    return _dependency


# Ready-made annotated dependencies for routers.  Each resolves to the
# authenticated User after enforcing the named permission.
RequireFinanceRead = Annotated[User, Depends(require_permission(Permission.FINANCE_READ))]
RequireFinanceWrite = Annotated[User, Depends(require_permission(Permission.FINANCE_WRITE))]
RequireFinanceReconcile = Annotated[
    User, Depends(require_permission(Permission.FINANCE_RECONCILE))
]
RequireCrmRead = Annotated[User, Depends(require_permission(Permission.CRM_READ))]
RequireCrmWrite = Annotated[User, Depends(require_permission(Permission.CRM_WRITE))]
RequireInventoryRead = Annotated[User, Depends(require_permission(Permission.INVENTORY_READ))]
RequireInventoryWrite = Annotated[User, Depends(require_permission(Permission.INVENTORY_WRITE))]
RequireIntelligenceRead = Annotated[
    User, Depends(require_permission(Permission.INTELLIGENCE_READ))
]
RequireIntelligenceAct = Annotated[
    User, Depends(require_permission(Permission.INTELLIGENCE_ACT))
]
RequireUserManage = Annotated[User, Depends(require_permission(Permission.USER_MANAGE))]
RequireAuditRead = Annotated[User, Depends(require_permission(Permission.AUDIT_READ))]
