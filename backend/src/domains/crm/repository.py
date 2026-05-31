import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domains.crm.models import Customer


class CustomerRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, customer_id: uuid.UUID) -> Customer | None:
        return await self._session.get(Customer, customer_id)

    async def get_by_email(self, email: str) -> Customer | None:
        result = await self._session.execute(select(Customer).where(Customer.email == email))
        return result.scalar_one_or_none()

    async def list_all(self, limit: int = 50, offset: int = 0) -> list[Customer]:
        result = await self._session.execute(
            select(Customer).order_by(Customer.created_at.desc()).limit(limit).offset(offset)
        )
        return list(result.scalars().all())

    async def create(self, customer: Customer) -> Customer:
        self._session.add(customer)
        await self._session.flush()
        await self._session.refresh(customer)
        return customer

    async def save(self, customer: Customer) -> Customer:
        await self._session.flush()
        await self._session.refresh(customer)
        return customer
