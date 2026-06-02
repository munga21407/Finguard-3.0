import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.domains.crm.schemas import CustomerCreate, CustomerResponse, CustomerUpdate
from src.domains.crm.service import CRMService
from src.infrastructure.database.postgres import get_db

router = APIRouter()

DBSession = Annotated[AsyncSession, Depends(get_db)]


@router.post("/customers", response_model=CustomerResponse, status_code=201)
async def create_customer(data: CustomerCreate, db: DBSession) -> CustomerResponse:
    customer = await CRMService(db).create_customer(data)
    return CustomerResponse.model_validate(customer)


@router.get("/customers", response_model=list[CustomerResponse])
async def list_customers(
    db: DBSession,
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
) -> list[CustomerResponse]:
    customers = await CRMService(db).list_customers(limit=limit, offset=offset)
    return [CustomerResponse.model_validate(c) for c in customers]


@router.get("/customers/{customer_id}", response_model=CustomerResponse)
async def get_customer(customer_id: uuid.UUID, db: DBSession) -> CustomerResponse:
    customer = await CRMService(db).get_customer(customer_id)
    return CustomerResponse.model_validate(customer)


@router.patch("/customers/{customer_id}", response_model=CustomerResponse)
async def update_customer(
    customer_id: uuid.UUID, data: CustomerUpdate, db: DBSession
) -> CustomerResponse:
    customer = await CRMService(db).update_customer(customer_id, data)
    return CustomerResponse.model_validate(customer)
