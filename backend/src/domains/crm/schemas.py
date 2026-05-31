import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr

from src.domains.crm.models import CustomerStatus, CustomerType


class CustomerCreate(BaseModel):
    name: str
    email: EmailStr
    phone: str | None = None
    customer_type: CustomerType = CustomerType.INDIVIDUAL
    notes: str | None = None


class CustomerUpdate(BaseModel):
    name: str | None = None
    phone: str | None = None
    status: CustomerStatus | None = None
    notes: str | None = None


class CustomerResponse(BaseModel):
    id: uuid.UUID
    name: str
    email: EmailStr
    phone: str | None
    customer_type: CustomerType
    status: CustomerStatus
    notes: str | None
    created_at: datetime

    model_config = {"from_attributes": True}
