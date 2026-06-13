import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.core.exceptions import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    TooManyRequestsError,
    UnauthorizedError,
)
from src.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from src.domains.identity.models import User, UserRole
from src.domains.identity.repository import UserRepository
from src.domains.identity.schemas import TokenResponse, UserCreate, UserUpdate
from src.infrastructure.cache.redis import get_auth_redis


class IdentityService:
    def __init__(self, session: AsyncSession) -> None:
        self._repo = UserRepository(session)
        self._session = session

    async def register(self, data: UserCreate) -> User:
        if await self._repo.get_by_email(data.email):
            raise ConflictError("Email already registered")

        # Bootstrap: the very first account in an empty system becomes a verified
        # OWNER so there is an initial administrator.  Every subsequent
        # self-registration is an UNVERIFIED VIEWER and cannot log in until an
        # administrator verifies it — closing the "anyone can register and touch
        # financial data" hole.
        is_first_user = (await self._repo.count()) == 0
        user = User(
            email=data.email,
            hashed_password=hash_password(data.password),
            full_name=data.full_name,
            role=UserRole.OWNER if is_first_user else UserRole.VIEWER,
            is_verified=is_first_user,
        )
        user = await self._repo.create(user)
        await self._session.commit()
        return user

    async def login(self, email: str, password: str) -> TokenResponse:
        redis = get_auth_redis()
        attempts_key = f"login_attempts:{email.lower()}"

        # Account lockout: reject before verifying the password once the failure
        # threshold is hit, so brute-force / credential-stuffing stops cold.
        attempts = int(await redis.get(attempts_key) or 0)
        if attempts >= settings.MAX_LOGIN_ATTEMPTS:
            raise TooManyRequestsError(
                "Account temporarily locked after too many failed login attempts. "
                f"Try again in {settings.LOCKOUT_DURATION_MINUTES} minutes."
            )

        user = await self._repo.get_by_email(email)
        if not user or not verify_password(password, user.hashed_password):
            await redis.incr(attempts_key)
            # Sliding window: each failed attempt extends the lock so a
            # persistent attacker stays locked out.
            await redis.expire(attempts_key, settings.LOCKOUT_DURATION_MINUTES * 60)
            raise UnauthorizedError("Invalid credentials")
        if not user.is_active:
            raise UnauthorizedError("Account disabled")
        if not user.is_verified:
            raise ForbiddenError("Account is pending verification by an administrator")

        await redis.delete(attempts_key)  # successful login clears the counter
        return TokenResponse(
            access_token=create_access_token(str(user.id), {"role": user.role}),
            refresh_token=create_refresh_token(str(user.id)),
        )

    # ── User administration (USER_MANAGE) ──────────────────────────────────────

    async def list_users(self, limit: int = 100, offset: int = 0) -> list[User]:
        return await self._repo.list_all(limit=limit, offset=offset)

    async def get_user(self, user_id: uuid.UUID) -> User:
        user = await self._repo.get_by_id(user_id)
        if not user:
            raise NotFoundError("User not found")
        return user

    async def update_user(self, user_id: uuid.UUID, data: UserUpdate) -> User:
        user = await self.get_user(user_id)
        for field, value in data.model_dump(exclude_none=True).items():
            setattr(user, field, value)
        user = await self._repo.save(user)
        await self._session.commit()
        return user

    async def refresh(self, refresh_token: str) -> TokenResponse:
        redis = get_auth_redis()
        payload = decode_token(refresh_token)
        if payload.get("type") != "refresh":
            raise UnauthorizedError("Invalid token type")

        jti = payload.get("jti")
        # Reuse detection: once a refresh token is used it is rotated and its jti
        # is blacklisted.  A second presentation of the same token (e.g. a
        # stolen copy) is therefore rejected.
        if jti is not None and await redis.exists(f"blacklist:{jti}"):
            raise UnauthorizedError("Refresh token has been revoked")

        user = await self._repo.get_by_id(uuid.UUID(str(payload["sub"])))
        if not user or not user.is_active:
            raise UnauthorizedError("User not found or disabled")

        # Rotate: blacklist the just-consumed refresh token so it cannot be replayed.
        if jti is not None:
            await self._blacklist_jti(redis, jti, payload.get("exp"))

        return TokenResponse(
            access_token=create_access_token(str(user.id), {"role": user.role}),
            refresh_token=create_refresh_token(str(user.id)),
        )

    @staticmethod
    async def _blacklist_jti(redis: Any, jti: str, exp: int | None) -> None:
        """Blacklist a token's jti in Redis until its natural expiry."""
        now_ts = int(datetime.now(UTC).timestamp())
        ttl = max(1, exp - now_ts) if exp else settings.REFRESH_TOKEN_EXPIRE_DAYS * 86_400
        await redis.setex(f"blacklist:{jti}", ttl, "1")
