from typing import Annotated

from fastapi import APIRouter, Depends, Request
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.domains.identity.schemas import (
    RefreshRequest,
    TokenRequest,
    TokenResponse,
    UserCreate,
    UserResponse,
)
from src.domains.identity.service import IdentityService
from src.infrastructure.database.postgres import get_db

limiter = Limiter(key_func=get_remote_address, storage_uri=settings.RATE_LIMIT_REDIS_URL)

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
