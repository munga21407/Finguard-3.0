"""
FastAPI dependency factories for the identity domain.

Provides `get_current_user` and the `CurrentUser` annotated type so
that other domains can protect routes without importing from core.security
directly.
"""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from src.core.exceptions import UnauthorizedException
from src.core.security import decode_token
from src.domains.identity.models import User
from src.domains.identity.repository import UserRepository
from src.infrastructure.database.postgres import get_db
from sqlalchemy.ext.asyncio import AsyncSession

_bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    if credentials is None:
        raise UnauthorizedException("Missing Authorization header")
    payload = decode_token(credentials.credentials)
    raw_id: str | None = payload.get("sub")
    if not raw_id:
        raise UnauthorizedException("Invalid token payload")
    user = await UserRepository(db).get_by_id(uuid.UUID(raw_id))
    if not user or not user.is_active:
        raise UnauthorizedException("User not found or inactive")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
