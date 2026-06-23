import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.domains.audit.models import AuditAction
from src.domains.audit.service import AuditService
from src.domains.crm.schemas import CustomerCreate, CustomerResponse, CustomerUpdate
from src.domains.crm.service import CRMService
from src.domains.identity.dependencies import RequireCrmRead, RequireCrmWrite
from src.infrastructure.database.postgres import get_db

router = APIRouter()

DBSession = Annotated[AsyncSession, Depends(get_db)]


@router.post("/customers", response_model=CustomerResponse, status_code=201)
async def create_customer(
    data: CustomerCreate, db: DBSession, current_user: RequireCrmWrite
) -> CustomerResponse:
    customer = await CRMService(db).create_customer(data)
    # Serialise before auditing: a best-effort audit write that fails rolls back
    # the session and would expire ``customer``, so build the response first.
    result = CustomerResponse.model_validate(customer)
    await AuditService(db).record_user_action_safe(
        current_user,
        AuditAction.CRM_CUSTOMER_CREATED,
        "customer",
        resource_id=customer.id,
        metadata={"name": customer.name},
    )
    return result


@router.get("/customers", response_model=list[CustomerResponse])
async def list_customers(
    db: DBSession,
    _: RequireCrmRead,
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
) -> list[CustomerResponse]:
    customers = await CRMService(db).list_customers(limit=limit, offset=offset)
    return [CustomerResponse.model_validate(c) for c in customers]


@router.get("/customers/{customer_id}", response_model=CustomerResponse)
async def get_customer(
    customer_id: uuid.UUID, db: DBSession, _: RequireCrmRead
) -> CustomerResponse:
    customer = await CRMService(db).get_customer(customer_id)
    return CustomerResponse.model_validate(customer)


@router.patch("/customers/{customer_id}", response_model=CustomerResponse)
async def update_customer(
    customer_id: uuid.UUID,
    data: CustomerUpdate,
    db: DBSession,
    current_user: RequireCrmWrite,
) -> CustomerResponse:
    customer = await CRMService(db).update_customer(customer_id, data)
    result = CustomerResponse.model_validate(customer)
    await AuditService(db).record_user_action_safe(
        current_user,
        AuditAction.CRM_CUSTOMER_UPDATED,
        "customer",
        resource_id=customer.id,
        metadata=data.model_dump(exclude_none=True, mode="json"),
    )
    return result
