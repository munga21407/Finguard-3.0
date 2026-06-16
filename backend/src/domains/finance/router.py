import hashlib
import hmac
import ipaddress
import uuid
from functools import lru_cache
from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.core.exceptions import UnprocessableError
from src.domains.finance.schemas import (
    BudgetCreate,
    BudgetResponse,
    ExpenseCreate,
    ExpenseResponse,
    InvoiceCreate,
    InvoiceEventResponse,
    InvoiceReconstructionResponse,
    InvoiceResponse,
    InvoiceUpdate,
    LedgerEntryCreate,
    LedgerEntryResponse,
    MpesaCallbackPayload,
    PaymentCreate,
    PaymentResponse,
    ReceiptExpenseCreate,
)
from src.domains.finance.service import FinanceService
from src.domains.identity.dependencies import RequireFinanceRead, RequireFinanceWrite
from src.infrastructure.database.postgres import get_db

router = APIRouter()
logger = structlog.get_logger(__name__)

DBSession = Annotated[AsyncSession, Depends(get_db)]


@lru_cache(maxsize=1)
def _mpesa_allowed_networks() -> tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]:
    """Parse MPESA_CALLBACK_ALLOWED_IPS into networks once (bare IPs → /32 or /128)."""
    networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
    for raw in settings.MPESA_CALLBACK_ALLOWED_IPS:
        entry = raw.strip()
        if not entry:
            continue
        try:
            networks.append(ipaddress.ip_network(entry, strict=False))
        except ValueError:
            logger.warning("mpesa: ignoring malformed allowlist entry", entry=entry)
    return tuple(networks)


def _callback_origin_ip(request: Request) -> str | None:
    """Source IP of the callback, honouring the trusted proxy's X-Forwarded-For.

    Behind nginx ``request.client.host`` is the proxy address, so the left-most
    X-Forwarded-For entry (set by the trusted proxy) identifies the real caller.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        first = forwarded.split(",")[0].strip()
        if first:
            return first
    return request.client.host if request.client else None


def _origin_allowed(ip_str: str | None) -> bool:
    if ip_str is None:
        return False
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    return any(ip in net for net in _mpesa_allowed_networks())


async def verify_mpesa_signature(
    request: Request,
    x_daraja_signature: Annotated[str | None, Header()] = None,
) -> None:
    """
    Authenticate an inbound Daraja STK Push callback.

    Safaricom does not HMAC-sign callbacks, so the primary control is an IP
    allowlist (MPESA_CALLBACK_ALLOWED_IPS) of Safaricom's published callback
    ranges.  The optional HMAC-SHA256 body signature (MPESA_CONSUMER_SECRET vs
    X-Daraja-Signature) is layered on as defence in depth and is enforced when a
    signature header is present, or as the sole control when no allowlist is set
    (e.g. a signing proxy in front of the app).

    Fail-closed: when NEITHER an allowlist nor a consumer secret is configured
    the endpoint refuses traffic (503) rather than processing unauthenticated
    callbacks.  Raises 403 on a disallowed origin or a bad signature.

    Body stream note: Starlette caches the body after the first await request.body()
    call, so FastAPI can still parse the JSON payload after this dependency runs.
    """
    networks = _mpesa_allowed_networks()
    has_secret = bool(settings.MPESA_CONSUMER_SECRET)

    if not networks and not has_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="M-Pesa callback authentication is not configured on this server",
        )

    # ── Primary control: source-IP allowlist ─────────────────────────────────
    if networks and not _origin_allowed(_callback_origin_ip(request)):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Callback origin is not in the M-Pesa allowlist",
        )

    # ── Optional HMAC signature ───────────────────────────────────────────────
    # Enforced when the provider sends a signature, or when it is the only
    # configured control (no allowlist). When an allowlist is configured and no
    # signature header is sent (real Daraja), the IP check above is sufficient.
    must_check_signature = has_secret and (x_daraja_signature is not None or not networks)
    if must_check_signature:
        if x_daraja_signature is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Missing X-Daraja-Signature header",
            )
        body: bytes = await request.body()
        key: bytes = settings.MPESA_CONSUMER_SECRET.encode()
        computed: str = hmac.new(key, body, hashlib.sha256).hexdigest()
        # Normalise the incoming signature to lowercase before constant-time
        # comparison so capitalisation differences do not cause false rejections.
        if not hmac.compare_digest(computed, x_daraja_signature.lower()):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Signature mismatch",
            )


# ── Ledger ────────────────────────────────────────────────────────────────────

@router.post("/ledger", response_model=LedgerEntryResponse, status_code=201)
async def post_ledger_entry(
    data: LedgerEntryCreate, db: DBSession, _: RequireFinanceWrite
) -> LedgerEntryResponse:
    entry = await FinanceService(db).post_ledger_entry(data)
    return LedgerEntryResponse.model_validate(entry)


# ── Invoices ──────────────────────────────────────────────────────────────────

@router.get("/invoices", response_model=list[InvoiceResponse])
async def list_invoices(
    db: DBSession,
    _: RequireFinanceRead,
    customer_id: Annotated[uuid.UUID | None, Query()] = None,
) -> list[InvoiceResponse]:
    invoices = await FinanceService(db).list_invoices(customer_id=customer_id)
    return [InvoiceResponse.model_validate(inv) for inv in invoices]


@router.get("/invoices/{invoice_id}", response_model=InvoiceResponse)
async def get_invoice(
    invoice_id: uuid.UUID, db: DBSession, _: RequireFinanceRead
) -> InvoiceResponse:
    invoice = await FinanceService(db).get_invoice(invoice_id)
    return InvoiceResponse.model_validate(invoice)


@router.post("/invoices", response_model=InvoiceResponse, status_code=201)
async def create_invoice(
    data: InvoiceCreate, db: DBSession, _: RequireFinanceWrite
) -> InvoiceResponse:
    invoice = await FinanceService(db).create_invoice(data)
    return InvoiceResponse.model_validate(invoice)


@router.patch("/invoices/{invoice_id}", response_model=InvoiceResponse)
async def update_invoice(
    invoice_id: uuid.UUID, data: InvoiceUpdate, db: DBSession, _: RequireFinanceWrite
) -> InvoiceResponse:
    invoice = await FinanceService(db).update_invoice(invoice_id, data)
    return InvoiceResponse.model_validate(invoice)


@router.post("/invoices/{invoice_id}/pay", response_model=InvoiceResponse)
async def mark_invoice_paid(
    invoice_id: uuid.UUID, db: DBSession, _: RequireFinanceWrite
) -> InvoiceResponse:
    invoice = await FinanceService(db).mark_invoice_paid(invoice_id)
    return InvoiceResponse.model_validate(invoice)


@router.get("/invoices/{invoice_id}/events", response_model=list[InvoiceEventResponse])
async def list_invoice_events(
    invoice_id: uuid.UUID, db: DBSession, _: RequireFinanceRead
) -> list[InvoiceEventResponse]:
    """Append-only event history for an invoice (issuance, payments), oldest first."""
    events = await FinanceService(db).get_invoice_events(invoice_id)
    return [InvoiceEventResponse.model_validate(e) for e in events]


@router.get(
    "/invoices/{invoice_id}/reconstruction",
    response_model=InvoiceReconstructionResponse,
)
async def reconstruct_invoice(
    invoice_id: uuid.UUID, db: DBSession, _: RequireFinanceRead
) -> InvoiceReconstructionResponse:
    """Fold the invoice's event log and compare it to the materialized row.

    Audit endpoint: ``matches_projection`` is true when the stored invoice equals
    the state derived purely from its events — proving the read model has not
    drifted from the append-only source of truth.
    """
    invoice, state, events = await FinanceService(db).reconstruct_invoice(invoice_id)
    matches = (
        state.amount_paid == invoice.amount_paid
        and state.balance_due == invoice.balance_due
        and (state.payment_status is None or state.payment_status == invoice.status)
    )
    return InvoiceReconstructionResponse(
        invoice_id=invoice.id,
        event_count=state.event_count,
        derived_total=state.total,
        derived_amount_paid=state.amount_paid,
        derived_balance_due=state.balance_due,
        derived_status=state.payment_status,
        stored_amount_paid=invoice.amount_paid,
        stored_balance_due=invoice.balance_due,
        stored_status=invoice.status,
        matches_projection=matches,
        events=[InvoiceEventResponse.model_validate(e) for e in events],
    )


# ── Expenses ──────────────────────────────────────────────────────────────────

@router.post("/expenses", response_model=ExpenseResponse, status_code=201)
async def create_expense(
    data: ExpenseCreate, db: DBSession, _: RequireFinanceWrite
) -> ExpenseResponse:
    expense = await FinanceService(db).create_expense(data)
    return ExpenseResponse.model_validate(expense)


@router.get("/expenses", response_model=list[ExpenseResponse])
async def list_expenses(
    db: DBSession,
    _: RequireFinanceRead,
    limit: int = Query(default=100, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[ExpenseResponse]:
    expenses = await FinanceService(db).list_expenses(limit=limit, offset=offset)
    return [ExpenseResponse.model_validate(e) for e in expenses]


@router.post("/receipts", response_model=ExpenseResponse, status_code=201)
async def create_receipt_expense(
    data: ReceiptExpenseCreate, db: DBSession, _: RequireFinanceWrite
) -> ExpenseResponse:
    """Persist a reviewed receipt scan as an expense.

    The OCR + categorisation happens in the intelligence domain
    (POST /intelligence/receipts/scan); this endpoint takes the user-verified
    fields and writes the expense (with budget burn-down + ``expenses.created``
    event) in a single transaction.
    """
    expense = await FinanceService(db).create_receipt_expense(data)
    return ExpenseResponse.model_validate(expense)


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

    A malformed or incomplete callback is rejected (not persisted) but still
    ACKed — retrying an unprocessable payload would never succeed, so we record
    the rejection in the logs rather than asking Daraja to resend it.
    """
    try:
        await FinanceService(db).process_mpesa_callback(payload)
    except UnprocessableError as exc:
        logger.warning("mpesa: callback rejected as unprocessable", detail=exc.detail)
    return {"ResultCode": 0, "ResultDesc": "Accepted"}


# ── Cash Payments ─────────────────────────────────────────────────────────────

@router.post("/payments/cash", response_model=PaymentResponse, status_code=201)
async def record_cash_payment(
    data: PaymentCreate,
    db: DBSession,
    current_user: RequireFinanceWrite,
) -> PaymentResponse:
    payment = await FinanceService(db).record_cash_payment(data, current_user)
    return PaymentResponse.model_validate(payment)


# ── Budgets ───────────────────────────────────────────────────────────────────

@router.post("/budgets", response_model=BudgetResponse, status_code=201)
async def create_budget(
    data: BudgetCreate, db: DBSession, _: RequireFinanceWrite
) -> BudgetResponse:
    budget = await FinanceService(db).create_budget(data)
    return BudgetResponse.model_validate(budget)


@router.get("/budgets", response_model=list[BudgetResponse])
async def list_budgets(db: DBSession, _: RequireFinanceRead) -> list[BudgetResponse]:
    budgets = await FinanceService(db).list_budgets()
    return [BudgetResponse.model_validate(b) for b in budgets]
