import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import ConflictException, NotFoundException
from src.domains.crm.models import Customer
from src.domains.crm.repository import CustomerRepository
from src.domains.crm.schemas import CustomerCreate, CustomerUpdate


class CRMService:
    def __init__(self, session: AsyncSession) -> None:
        self._repo = CustomerRepository(session)
        self._session = session

    async def create_customer(self, data: CustomerCreate) -> Customer:
        if await self._repo.get_by_email(data.email):
            raise ConflictException("Customer with this email already exists")
        customer = Customer(**data.model_dump())
        customer = await self._repo.create(customer)
        await self._session.commit()
        return customer

    async def get_customer(self, customer_id: uuid.UUID) -> Customer:
        customer = await self._repo.get_by_id(customer_id)
        if not customer:
            raise NotFoundException("Customer not found")
        return customer

    async def list_customers(self, limit: int = 50, offset: int = 0) -> list[Customer]:
        return await self._repo.list_all(limit=limit, offset=offset)

    async def update_customer(self, customer_id: uuid.UUID, data: CustomerUpdate) -> Customer:
        customer = await self.get_customer(customer_id)
        for field, value in data.model_dump(exclude_none=True).items():
            setattr(customer, field, value)
        customer = await self._repo.save(customer)
        await self._session.commit()
        return customer
