import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from src.domains.finance.models import InvoiceStatus, PaymentMethod, TransactionType


class LedgerEntryCreate(BaseModel):
    account_id: uuid.UUID
    customer_id: uuid.UUID | None = None
    transaction_type: TransactionType
    amount: Decimal = Field(gt=0)
    currency: str = "KES"
    description: str | None = None
    reference: str | None = None


class LedgerEntryResponse(BaseModel):
    id: uuid.UUID
    account_id: uuid.UUID
    customer_id: uuid.UUID | None
    transaction_type: TransactionType
    amount: Decimal
    currency: str
    description: str | None
    reference: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class InvoiceCreate(BaseModel):
    customer_id: uuid.UUID
    invoice_number: str
    subtotal: Decimal = Field(gt=0)
    tax: Decimal = Field(ge=0, default=Decimal("0"))
    currency: str = "KES"
    due_date: datetime | None = None
    notes: str | None = None


class InvoiceUpdate(BaseModel):
    status: InvoiceStatus | None = None
    notes: str | None = None
    paid_at: datetime | None = None


class InvoiceResponse(BaseModel):
    id: uuid.UUID
    customer_id: uuid.UUID
    invoice_number: str
    status: InvoiceStatus
    subtotal: Decimal
    tax: Decimal
    total: Decimal
    currency: str
    due_date: datetime | None
    paid_at: datetime | None
    notes: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class BudgetCreate(BaseModel):
    name: str
    category: str
    amount: Decimal = Field(gt=0)
    currency: str = "KES"
    period_start: datetime
    period_end: datetime


class BudgetResponse(BaseModel):
    id: uuid.UUID
    name: str
    category: str
    amount: Decimal
    spent: Decimal
    currency: str
    period_start: datetime
    period_end: datetime
    created_at: datetime

    model_config = {"from_attributes": True}
