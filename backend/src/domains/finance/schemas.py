import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from src.domains.finance.models import InvoiceStatus, PaymentMethod, TransactionType
from src.domains.finance.types import VaultType


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


# ── Expenses ──────────────────────────────────────────────────────────────────

class ExpenseCreate(BaseModel):
    expense_ref: str | None = None
    customer_id: uuid.UUID | None = None
    category: str
    amount: Decimal = Field(gt=0)
    vault: VaultType
    mpesa_trans_id: uuid.UUID | None = None
    invoice_id: uuid.UUID | None = None


class ExpenseResponse(BaseModel):
    id: uuid.UUID
    expense_ref: str | None
    customer_id: uuid.UUID | None
    category: str
    amount: Decimal
    vault: VaultType
    mpesa_trans_id: uuid.UUID | None
    invoice_id: uuid.UUID | None
    created_at: datetime

    model_config = {"from_attributes": True}


# ── M-Pesa ────────────────────────────────────────────────────────────────────

class MpesaCallbackItem(BaseModel):
    Name: str
    Value: str | int | float | None = None


class MpesaCallbackMetadata(BaseModel):
    Item: list[MpesaCallbackItem] = []


class MpesaStkCallback(BaseModel):
    MerchantRequestID: str
    CheckoutRequestID: str
    ResultCode: int
    ResultDesc: str
    CallbackMetadata: MpesaCallbackMetadata | None = None


class MpesaCallbackPayload(BaseModel):
    """Daraja STK Push callback envelope."""

    Body: dict  # accept raw Body; validated fields extracted in service


class MpesaTransactionResponse(BaseModel):
    id: uuid.UUID
    trans_id: str
    amount: Decimal
    phone: str
    bill_ref: str | None
    vault: VaultType
    is_reconciled: bool
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
