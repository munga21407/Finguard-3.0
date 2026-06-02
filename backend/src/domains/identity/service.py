from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import ConflictError, UnauthorizedError
from src.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from src.domains.identity.models import User
from src.domains.identity.repository import UserRepository
from src.domains.identity.schemas import TokenResponse, UserCreate


class IdentityService:
    def __init__(self, session: AsyncSession) -> None:
        self._repo = UserRepository(session)
        self._session = session

    async def register(self, data: UserCreate) -> User:
        if await self._repo.get_by_email(data.email):
            raise ConflictError("Email already registered")
        user = User(
            email=data.email,
            hashed_password=hash_password(data.password),
            full_name=data.full_name,
        )
        user = await self._repo.create(user)
        await self._session.commit()
        return user

    async def login(self, email: str, password: str) -> TokenResponse:
        user = await self._repo.get_by_email(email)
        if not user or not verify_password(password, user.hashed_password):
            raise UnauthorizedError("Invalid credentials")
        if not user.is_active:
            raise UnauthorizedError("Account disabled")
        return TokenResponse(
            access_token=create_access_token(str(user.id), {"role": user.role}),
            refresh_token=create_refresh_token(str(user.id)),
        )

    async def refresh(self, refresh_token: str) -> TokenResponse:
        payload = decode_token(refresh_token)
        if payload.get("type") != "refresh":
            raise UnauthorizedError("Invalid token type")
        user = await self._repo.get_by_id(payload["sub"])  # type: ignore[arg-type]
        if not user or not user.is_active:
            raise UnauthorizedError("User not found or disabled")
        return TokenResponse(
            access_token=create_access_token(str(user.id), {"role": user.role}),
            refresh_token=create_refresh_token(str(user.id)),
        )
