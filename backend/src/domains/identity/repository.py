import uuid
from collections.abc import Collection

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domains.identity.models import User, UserRole


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, user_id: uuid.UUID) -> User | None:
        return await self._session.get(User, user_id)

    async def get_by_email(self, email: str) -> User | None:
        result = await self._session.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()

    async def count(self) -> int:
        return (await self._session.scalar(select(func.count()).select_from(User))) or 0

    async def list_all(self, limit: int = 100, offset: int = 0) -> list[User]:
        result = await self._session.execute(
            select(User).order_by(User.created_at.asc()).limit(limit).offset(offset)
        )
        return list(result.scalars().all())

    async def list_active_by_roles(self, roles: Collection[UserRole]) -> list[User]:
        """Active, verified users in any of *roles* — the candidate reviewers for
        an approval notification. Empty *roles* returns nothing (no fan-out)."""
        if not roles:
            return []
        result = await self._session.execute(
            select(User).where(
                User.role.in_(roles),
                User.is_active.is_(True),
                User.is_verified.is_(True),
            )
        )
        return list(result.scalars().all())

    async def create(self, user: User) -> User:
        self._session.add(user)
        await self._session.flush()
        await self._session.refresh(user)
        return user

    async def save(self, user: User) -> User:
        await self._session.flush()
        await self._session.refresh(user)
        return user
