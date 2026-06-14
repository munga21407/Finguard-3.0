import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field

from src.domains.finance.models import InvoiceEventType, InvoiceStatus, TransactionType
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
    amount_paid: Decimal
    balance_due: Decimal
    currency: str
    due_date: datetime | None
    paid_at: datetime | None
    notes: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Invoice event log (event sourcing) ────────────────────────────────────────

class InvoiceEventResponse(BaseModel):
    id: uuid.UUID
    invoice_id: uuid.UUID
    sequence: int
    event_type: InvoiceEventType
    amount: Decimal
    payload: dict[str, Any]
    occurred_at: datetime
    recorded_by: uuid.UUID | None
    created_at: datetime

    model_config = {"from_attributes": True}


class InvoiceReconstructionResponse(BaseModel):
    """An invoice's event history plus the state derived by folding it.

    ``matches_projection`` lets an auditor confirm the stored (materialized)
    invoice row equals the fold of its events — i.e. the read model has not
    drifted from the append-only source of truth.
    """

    invoice_id: uuid.UUID
    event_count: int
    # State derived purely from the event log.
    derived_total: Decimal
    derived_amount_paid: Decimal
    derived_balance_due: Decimal
    derived_status: InvoiceStatus | None
    # The current materialized values, for side-by-side comparison.
    stored_amount_paid: Decimal
    stored_balance_due: Decimal
    stored_status: InvoiceStatus
    matches_projection: bool
    events: list[InvoiceEventResponse]


# ── Expenses ──────────────────────────────────────────────────────────────────

class ExpenseCreate(BaseModel):
    expense_ref: str | None = None
    customer_id: uuid.UUID | None = None
    category: str
    amount: Decimal = Field(gt=0)
    vault: VaultType
    mpesa_trans_id: uuid.UUID | None = None
    invoice_id: uuid.UUID | None = None


class ReceiptExpenseCreate(BaseModel):
    """Reviewed receipt-scan fields submitted to POST /finance/receipts.

    Produced by the frontend after the user verifies the OCR output from
    POST /intelligence/receipts/scan.  ``vault`` defaults to CASH because a
    scanned paper receipt is overwhelmingly a cash purchase; the user can
    override it.
    """
    merchant_name: str | None = None
    category: str = Field(min_length=1, max_length=100)
    amount: Decimal = Field(gt=0)
    vault: VaultType = VaultType.CASH
    kra_pin: str | None = Field(default=None, max_length=20)
    receipt_date: datetime | None = None
    description: str | None = None
    expense_ref: str | None = Field(default=None, max_length=50)
    customer_id: uuid.UUID | None = None


class ExpenseResponse(BaseModel):
    id: uuid.UUID
    expense_ref: str | None
    customer_id: uuid.UUID | None
    category: str
    amount: Decimal
    vault: VaultType
    mpesa_trans_id: uuid.UUID | None
    invoice_id: uuid.UUID | None
    merchant_name: str | None = None
    kra_pin: str | None = None
    description: str | None = None
    receipt_date: datetime | None = None
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

    Body: dict[str, Any]  # accept raw Body; validated fields extracted in service


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


# ── Cash Payments ─────────────────────────────────────────────────────────────

class PaymentCreate(BaseModel):
    invoice_id: uuid.UUID
    amount: Decimal = Field(gt=0, description="Must be greater than zero")
    # Literal enforces CASH-only at parse time — M-Pesa payments arrive via Daraja webhook.
    vault: Literal[VaultType.CASH] = VaultType.CASH
    reference_note: str | None = None
    payment_date: datetime


class PaymentResponse(BaseModel):
    id: uuid.UUID
    invoice_id: uuid.UUID
    amount: Decimal
    vault: VaultType
    reference_note: str | None
    payment_date: datetime
    recorded_by: uuid.UUID
    created_at: datetime

    model_config = {"from_attributes": True}
