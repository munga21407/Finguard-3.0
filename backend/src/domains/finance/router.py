import hashlib
import hmac
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.domains.finance.schemas import (
    BudgetCreate,
    BudgetResponse,
    ExpenseCreate,
    ExpenseResponse,
    InvoiceCreate,
    InvoiceResponse,
    InvoiceUpdate,
    LedgerEntryCreate,
    LedgerEntryResponse,
    MpesaCallbackPayload,
    PaymentCreate,
    PaymentResponse,
)
from src.domains.finance.service import FinanceService
from src.domains.identity.dependencies import CurrentUser
from src.infrastructure.database.postgres import get_db

router = APIRouter()

DBSession = Annotated[AsyncSession, Depends(get_db)]


async def verify_mpesa_signature(
    request: Request,
    x_daraja_signature: Annotated[str | None, Header()] = None,
) -> None:
    """
    Verify that this Daraja callback was signed by Safaricom.

    Computes HMAC-SHA256 over the raw request body using MPESA_CONSUMER_SECRET
    and compares against the X-Daraja-Signature header with hmac.compare_digest
    to prevent timing-based side-channel attacks.

    Raises 503 when M-Pesa credentials are not configured (rather than a
    misleading 403) so operators can diagnose misconfiguration immediately.
    Raises 403 on a missing or non-matching signature.

    Body stream note: Starlette caches the body after the first await request.body()
    call, so FastAPI can still parse the JSON payload after this dependency runs.
    """
    if not settings.MPESA_CONSUMER_SECRET:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="M-Pesa integration is not configured on this server",
        )
    if x_daraja_signature is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Missing X-Daraja-Signature header",
        )
    body: bytes = await request.body()
    key: bytes = settings.MPESA_CONSUMER_SECRET.encode()
    computed: str = hmac.new(key, body, hashlib.sha256).hexdigest()
    # Normalise the incoming signature to lowercase before constant-time comparison
    # so capitalisation differences do not cause false rejections.
    if not hmac.compare_digest(computed, x_daraja_signature.lower()):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Signature mismatch",
        )


# ── Ledger ────────────────────────────────────────────────────────────────────

@router.post("/ledger", response_model=LedgerEntryResponse, status_code=201)
async def post_ledger_entry(
    data: LedgerEntryCreate, db: DBSession, _: CurrentUser
) -> LedgerEntryResponse:
    entry = await FinanceService(db).post_ledger_entry(data)
    return LedgerEntryResponse.model_validate(entry)


# ── Invoices ──────────────────────────────────────────────────────────────────

@router.get("/invoices", response_model=list[InvoiceResponse])
async def list_invoices(
    db: DBSession,
    _: CurrentUser,
    customer_id: Annotated[uuid.UUID | None, Query()] = None,
) -> list[InvoiceResponse]:
    invoices = await FinanceService(db).list_invoices(customer_id=customer_id)
    return [InvoiceResponse.model_validate(inv) for inv in invoices]


@router.get("/invoices/{invoice_id}", response_model=InvoiceResponse)
async def get_invoice(invoice_id: uuid.UUID, db: DBSession, _: CurrentUser) -> InvoiceResponse:
    invoice = await FinanceService(db).get_invoice(invoice_id)
    return InvoiceResponse.model_validate(invoice)


@router.post("/invoices", response_model=InvoiceResponse, status_code=201)
async def create_invoice(
    data: InvoiceCreate, db: DBSession, _: CurrentUser
) -> InvoiceResponse:
    invoice = await FinanceService(db).create_invoice(data)
    return InvoiceResponse.model_validate(invoice)


@router.patch("/invoices/{invoice_id}", response_model=InvoiceResponse)
async def update_invoice(
    invoice_id: uuid.UUID, data: InvoiceUpdate, db: DBSession, _: CurrentUser
) -> InvoiceResponse:
    invoice = await FinanceService(db).update_invoice(invoice_id, data)
    return InvoiceResponse.model_validate(invoice)


@router.post("/invoices/{invoice_id}/pay", response_model=InvoiceResponse)
async def mark_invoice_paid(
    invoice_id: uuid.UUID, db: DBSession, _: CurrentUser
) -> InvoiceResponse:
    invoice = await FinanceService(db).mark_invoice_paid(invoice_id)
    return InvoiceResponse.model_validate(invoice)


# ── Expenses ──────────────────────────────────────────────────────────────────

@router.post("/expenses", response_model=ExpenseResponse, status_code=201)
async def create_expense(
    data: ExpenseCreate, db: DBSession, _: CurrentUser
) -> ExpenseResponse:
    expense = await FinanceService(db).create_expense(data)
    return ExpenseResponse.model_validate(expense)


@router.get("/expenses", response_model=list[ExpenseResponse])
async def list_expenses(
    db: DBSession,
    _: CurrentUser,
    limit: int = Query(default=100, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[ExpenseResponse]:
    expenses = await FinanceService(db).list_expenses(limit=limit, offset=offset)
    return [ExpenseResponse.model_validate(e) for e in expenses]


# ── M-Pesa ────────────────────────────────────────────────────────────────────

@router.post(
    "/mpesa/callback",
    status_code=200,
    dependencies=[Depends(verify_mpesa_signature)],
)
async def mpesa_callback(
    payload: MpesaCallbackPayload, db: DBSession
) -> dict[str, Any]:
    """
    Daraja STK Push callback endpoint.
    HMAC-SHA256 signature is verified by the verify_mpesa_signature dependency
    before this handler executes. Returns 200 immediately to satisfy Daraja's
    ACK requirement regardless of downstream processing outcome.
    """
    await FinanceService(db).process_mpesa_callback(payload)
    return {"ResultCode": 0, "ResultDesc": "Accepted"}


# ── Cash Payments ─────────────────────────────────────────────────────────────

@router.post("/payments/cash", response_model=PaymentResponse, status_code=201)
async def record_cash_payment(
    data: PaymentCreate,
    db: DBSession,
    current_user: CurrentUser,
) -> PaymentResponse:
    payment = await FinanceService(db).record_cash_payment(data, current_user)
    return PaymentResponse.model_validate(payment)


# ── Budgets ───────────────────────────────────────────────────────────────────

@router.post("/budgets", response_model=BudgetResponse, status_code=201)
async def create_budget(
    data: BudgetCreate, db: DBSession, _: CurrentUser
) -> BudgetResponse:
    budget = await FinanceService(db).create_budget(data)
    return BudgetResponse.model_validate(budget)


@router.get("/budgets", response_model=list[BudgetResponse])
async def list_budgets(db: DBSession, _: CurrentUser) -> list[BudgetResponse]:
    budgets = await FinanceService(db).list_budgets()
    return [BudgetResponse.model_validate(b) for b in budgets]
