import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

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


class InvoiceSettleRequest(BaseModel):
    """Body for ``POST /invoices/{id}/pay`` — settle the outstanding balance.

    ``vault`` is the settlement rail the money came in on; it is recorded on the
    resulting Payment so the cash lands in the right vault.  Defaults to CASH (the
    typical manual settlement) when the body is omitted.
    """

    vault: VaultType = VaultType.CASH
    reference_note: str | None = None


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
    # NULL for agent-applied reconciliation payments (no human actor).
    recorded_by: uuid.UUID | None
    # Provenance of a reconciled payment (NULL for manual cash).
    mpesa_trans_id: uuid.UUID | None = None
    bank_line_id: uuid.UUID | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Bank statement import (Agent C reconciliation source) ─────────────────────

class BankStatementLineImport(BaseModel):
    """One bank statement line submitted to POST /finance/reconciliation/bank-statements/import.

    Lines land unreconciled; Agent C later matches them to open invoices (amount
    + date + reference_text ↔ invoice_number) and records a Payment(vault=BANK).

    ``external_ref`` is the bank's own line/transaction reference and is REQUIRED:
    it is the import idempotency key, so re-importing a line whose ``external_ref``
    already exists is skipped and the same statement can be uploaded twice without
    duplicating lines (or double-paying invoices).
    """

    amount: Decimal = Field(gt=0)
    date: datetime
    reference_text: str | None = None
    external_ref: str = Field(min_length=1, max_length=255)


class BankStatementLineResponse(BaseModel):
    id: uuid.UUID
    amount: Decimal
    date: datetime
    reference_text: str | None
    external_ref: str
    imported_by: uuid.UUID | None
    review_status: str
    approved_by: uuid.UUID | None
    approved_at: datetime | None
    is_reconciled: bool
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Reconciliation flow (Sankey) ──────────────────────────────────────────────

class SankeyNode(BaseModel):
    """A single node in the invoice-lifecycle → settlement Sankey diagram."""

    name: str
    # Stage tag the frontend uses for colour-coding the three columns.
    kind: Literal["source", "status", "rail"]


class SankeyLink(BaseModel):
    """A weighted flow between two nodes, referenced by their index in ``nodes``."""

    source: int
    target: int
    value: Decimal


class ReconciliationFlowResponse(BaseModel):
    """Sankey-ready Accounts-Receivable flow for the Overview dashboard.

    Three stages:

      Stage 1  ``Total Billed`` — Σ invoice.total over non-cancelled invoices.
      Stage 2  Invoice status (Draft / Sent / Overdue / Partially Paid / Paid).
               These amounts are the *projection* of folding the append-only
               ``invoice_events`` log (the materialized ``invoices`` row is kept
               in sync with that fold), so the column reflects the lifecycle
               transitions draft → sent → paid / partially_paid / overdue.
      Stage 3  Settlement rail, read from the per-invoice ``Payment`` rows grouped
               by their invoice's status and rail (vault): ``M-Pesa`` / ``Bank``
               (the reconciled rails, produced by Agent C) and ``Cash``.  Every
               settlement creates a Payment, so the rails fully account for each
               status's collected total.

    Both stages are exact.  ``nodes``/``links`` are empty when nothing has been
    billed yet.
    """

    nodes: list[SankeyNode]
    links: list[SankeyLink]
    currency: str
    total_billed: Decimal
    total_collected: Decimal
    reconciled_total: Decimal


# ── Vault transfers + per-vault balances (treasury) ───────────────────────────

class VaultTransferCreate(BaseModel):
    """Record an internal movement of the business's own money between vaults.

    ``fee`` (optional M-Pesa/bank charge) is booked as a separate Expense on the
    source vault, so it reduces the source balance and shows up in spend.
    """

    from_vault: VaultType
    to_vault: VaultType
    amount: Decimal = Field(gt=0)
    fee: Decimal = Field(ge=0, default=Decimal("0"))
    reference_note: str | None = None
    occurred_at: datetime

    @model_validator(mode="after")
    def _distinct_vaults(self) -> "VaultTransferCreate":
        if self.from_vault == self.to_vault:
            raise ValueError("from_vault and to_vault must differ")
        return self


class VaultTransferResponse(BaseModel):
    id: uuid.UUID
    from_vault: VaultType
    to_vault: VaultType
    amount: Decimal
    fee: Decimal
    reference_note: str | None
    occurred_at: datetime
    recorded_by: uuid.UUID | None
    fee_expense_id: uuid.UUID | None
    created_at: datetime

    model_config = {"from_attributes": True}


class VaultBalance(BaseModel):
    vault: VaultType
    balance: Decimal


class VaultBalancesResponse(BaseModel):
    """Live balance of each vault, derived from payments, expenses and transfers.

    ``balance = Σ payments_in + Σ transfers_in − Σ expenses − Σ transfers_out``
    (transfer fees are captured by the expense term).  Always lists every
    ``VaultType`` member; ``total`` is the sum (the overall cash position).
    """

    balances: list[VaultBalance]
    currency: str
    total: Decimal
