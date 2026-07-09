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
from src.domains.audit.models import AuditAction
from src.domains.audit.service import AuditService
from src.domains.finance.models import ExpenseApprovalStatus
from src.domains.finance.schemas import (
    BankStatementLineImport,
    BankStatementLineResponse,
    BudgetCreate,
    BudgetResponse,
    CreditNoteRequest,
    ExpenseCreate,
    ExpenseResponse,
    FinancialReport,
    InvoiceCancelRequest,
    InvoiceCogsResponse,
    InvoiceCreate,
    InvoiceEventResponse,
    InvoiceReconstructionResponse,
    InvoiceResponse,
    InvoiceSettleRequest,
    InvoiceUpdate,
    LedgerEntryCreate,
    LedgerEntryResponse,
    MpesaCallbackPayload,
    PayableCreate,
    PayableQueueResponse,
    PayableResponse,
    PayableScheduleRequest,
    PaymentCreate,
    PaymentResponse,
    ReceiptExpenseCreate,
    ReconciliationFlowResponse,
    ReportCatalogResponse,
    ReportType,
    StockPurchaseCreate,
    StockPurchaseResponse,
    VaultBalancesResponse,
    VaultTransferCreate,
    VaultTransferResponse,
)
from src.domains.finance.service import FinanceService
from src.domains.identity.dependencies import (
    RequireFinanceApprove,
    RequireFinanceRead,
    RequireFinanceReconcile,
    RequireFinanceWrite,
)
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
    data: InvoiceCreate, db: DBSession, current_user: RequireFinanceWrite
) -> InvoiceResponse:
    invoice = await FinanceService(db).create_invoice(data)
    # Serialise before auditing: a best-effort audit write that fails rolls back
    # the session and would expire ``invoice``, so build the response first.
    result = InvoiceResponse.model_validate(invoice)
    await AuditService(db).record_user_action_safe(
        current_user,
        AuditAction.INVOICE_CREATED,
        "invoice",
        resource_id=invoice.id,
        metadata={"invoice_number": invoice.invoice_number, "total": str(invoice.total)},
    )
    return result


@router.patch("/invoices/{invoice_id}", response_model=InvoiceResponse)
async def update_invoice(
    invoice_id: uuid.UUID,
    data: InvoiceUpdate,
    db: DBSession,
    current_user: RequireFinanceWrite,
) -> InvoiceResponse:
    invoice = await FinanceService(db).update_invoice(invoice_id, data)
    result = InvoiceResponse.model_validate(invoice)
    await AuditService(db).record_user_action_safe(
        current_user,
        AuditAction.INVOICE_UPDATED,
        "invoice",
        resource_id=invoice.id,
        metadata=data.model_dump(exclude_none=True, mode="json"),
    )
    return result


@router.post("/invoices/{invoice_id}/pay", response_model=InvoiceResponse)
async def mark_invoice_paid(
    invoice_id: uuid.UUID,
    db: DBSession,
    current_user: RequireFinanceWrite,
    data: InvoiceSettleRequest | None = None,
) -> InvoiceResponse:
    """Settle an invoice's outstanding balance on the chosen rail.

    The optional body picks the settlement ``vault`` (M-Pesa / Cash / Bank); the
    money is recorded as a Payment on that vault.  Defaults to CASH when omitted.
    """
    settle = data or InvoiceSettleRequest()
    invoice = await FinanceService(db).mark_invoice_paid(
        invoice_id, current_user, vault=settle.vault, reference_note=settle.reference_note
    )
    result = InvoiceResponse.model_validate(invoice)
    await AuditService(db).record_user_action_safe(
        current_user,
        AuditAction.INVOICE_PAID,
        "invoice",
        resource_id=invoice.id,
        metadata={"vault": settle.vault.value, "status": invoice.status.value},
    )
    return result


@router.post("/invoices/{invoice_id}/credit-note", response_model=InvoiceResponse)
async def apply_credit_note(
    invoice_id: uuid.UUID,
    data: CreditNoteRequest,
    db: DBSession,
    current_user: RequireFinanceWrite,
) -> InvoiceResponse:
    """Reduce an invoice's receivable by a credit note (event-sourced)."""
    invoice = await FinanceService(db).apply_credit_note(
        invoice_id, data.amount, current_user, reason=data.reason
    )
    result = InvoiceResponse.model_validate(invoice)
    await AuditService(db).record_user_action_safe(
        current_user,
        AuditAction.CREDIT_NOTE_APPLIED,
        "invoice",
        resource_id=invoice.id,
        metadata={"amount": str(data.amount), "reason": data.reason},
    )
    return result


@router.post("/invoices/{invoice_id}/cancel", response_model=InvoiceResponse)
async def cancel_invoice(
    invoice_id: uuid.UUID,
    db: DBSession,
    current_user: RequireFinanceWrite,
    data: InvoiceCancelRequest | None = None,
) -> InvoiceResponse:
    """Void an uncollectable invoice (terminal, event-sourced)."""
    body = data or InvoiceCancelRequest()
    invoice = await FinanceService(db).cancel_invoice(invoice_id, current_user, reason=body.reason)
    result = InvoiceResponse.model_validate(invoice)
    await AuditService(db).record_user_action_safe(
        current_user,
        AuditAction.INVOICE_CANCELLED,
        "invoice",
        resource_id=invoice.id,
        metadata={"reason": body.reason},
    )
    return result


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
        and state.credited == invoice.amount_credited
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


# ── Reconciliation ────────────────────────────────────────────────────────────


@router.get("/reconciliation-flow", response_model=ReconciliationFlowResponse)
async def reconciliation_flow(db: DBSession, _: RequireFinanceRead) -> ReconciliationFlowResponse:
    """Invoice-lifecycle → settlement-rail Sankey for the Overview dashboard.

    Stage 1 (Total Billed) → Stage 2 (current invoice status, the projection of
    the append-only ``invoice_events`` fold) → Stage 3 (settlement rail). Stage 3
    reads the per-invoice ``Payment`` rows produced by Agent C reconciliation
    (M-Pesa / Bank) and cash/manual settlement — every collected shilling is backed
    by a Payment, so the rails fully account for each status's collected total.
    """
    return await FinanceService(db).get_reconciliation_flow()


@router.get("/reports", response_model=ReportCatalogResponse)
async def report_catalog(
    db: DBSession,
    _: RequireFinanceRead,
    period_days: int = Query(365, ge=1, le=1825),
) -> ReportCatalogResponse:
    """List the CoreReports with a live ready/no_data status (drives the menu)."""
    return await FinanceService(db).get_report_catalog(period_days)


@router.get("/reports/{report_type}", response_model=FinancialReport)
async def generate_report(
    report_type: ReportType,
    db: DBSession,
    _: RequireFinanceRead,
    period_days: int = Query(365, ge=1, le=1825),
) -> FinancialReport:
    """Generate one financial report (P&L / cash-flow / tax) from live data."""
    return await FinanceService(db).generate_report(report_type, period_days)


@router.post(
    "/reconciliation/bank-statements/import",
    response_model=list[BankStatementLineResponse],
    status_code=201,
)
async def import_bank_statements(
    lines: list[BankStatementLineImport], db: DBSession, current_user: RequireFinanceReconcile
) -> list[BankStatementLineResponse]:
    """Ingest bank statement lines for Agent C to reconcile against open invoices.

    Requires ``finance:reconcile`` (manager+), not just ``finance:write`` — importing
    settlement data auto-marks invoices paid, so it is separated from ordinary
    finance operators (an Accountant cannot import settlements unilaterally).

    Lines land unreconciled; the batch bank-reconciliation job (or the Agent C
    LangGraph node) later matches them to invoices and records a Payment(vault=BANK).
    The importing user is recorded on each line for auditability.
    """
    rows = await FinanceService(db).import_bank_statement_lines(lines, current_user)
    return [BankStatementLineResponse.model_validate(r) for r in rows]


@router.get(
    "/reconciliation/bank-statements",
    response_model=list[BankStatementLineResponse],
)
async def list_bank_statements(
    db: DBSession,
    _: RequireFinanceRead,
    review_status: str | None = Query(default=None),
    limit: int = Query(default=100, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[BankStatementLineResponse]:
    """List imported bank statement lines, newest first (optionally by review status)."""
    lines = await FinanceService(db).list_bank_statement_lines(
        review_status=review_status, limit=limit, offset=offset
    )
    return [BankStatementLineResponse.model_validate(line) for line in lines]


@router.post(
    "/reconciliation/bank-statements/{line_id}/approve",
    response_model=BankStatementLineResponse,
)
async def approve_bank_statement_line(
    line_id: uuid.UUID, db: DBSession, current_user: RequireFinanceReconcile
) -> BankStatementLineResponse:
    """Approve a pending bank line so the reconciler may settle invoices with it.

    Maker-checker: the approver must differ from the importer (403 otherwise), so
    no single user can both import and release settlement data.
    """
    line = await FinanceService(db).approve_bank_statement_line(line_id, current_user)
    return BankStatementLineResponse.model_validate(line)


@router.post(
    "/reconciliation/bank-statements/{line_id}/reject",
    response_model=BankStatementLineResponse,
)
async def reject_bank_statement_line(
    line_id: uuid.UUID, db: DBSession, current_user: RequireFinanceReconcile
) -> BankStatementLineResponse:
    """Reject a pending bank line so it is never reconciled (approver ≠ importer)."""
    line = await FinanceService(db).reject_bank_statement_line(line_id, current_user)
    return BankStatementLineResponse.model_validate(line)


# ── Vault transfers + balances (treasury) ─────────────────────────────────────


@router.get("/vault-balances", response_model=VaultBalancesResponse)
async def vault_balances(db: DBSession, _: RequireFinanceRead) -> VaultBalancesResponse:
    """Live balance of each vault (M-Pesa / Cash / Bank) and the total cash position.

    Derived from payments (in), expenses (out), and vault transfers (in/out) — see
    ``FinanceService.get_vault_balances``.
    """
    return await FinanceService(db).get_vault_balances()


@router.post("/vault-transfers", response_model=VaultTransferResponse, status_code=201)
async def create_vault_transfer(
    data: VaultTransferCreate, db: DBSession, current_user: RequireFinanceWrite
) -> VaultTransferResponse:
    """Move the business's own money between vaults (net-zero to total cash).

    An optional ``fee`` is booked as an Expense on the source vault.
    """
    transfer = await FinanceService(db).create_vault_transfer(data, current_user)
    return VaultTransferResponse.model_validate(transfer)


@router.get("/vault-transfers", response_model=list[VaultTransferResponse])
async def list_vault_transfers(
    db: DBSession,
    _: RequireFinanceRead,
    limit: int = Query(default=100, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[VaultTransferResponse]:
    """Recent vault transfers, newest first."""
    transfers = await FinanceService(db).list_vault_transfers(limit=limit, offset=offset)
    return [VaultTransferResponse.model_validate(t) for t in transfers]


# ── Expenses ──────────────────────────────────────────────────────────────────


@router.post("/expenses", response_model=ExpenseResponse, status_code=201)
async def create_expense(
    data: ExpenseCreate, db: DBSession, current_user: RequireFinanceWrite
) -> ExpenseResponse:
    expense = await FinanceService(db).create_expense(data)
    result = ExpenseResponse.model_validate(expense)
    await AuditService(db).record_user_action_safe(
        current_user,
        AuditAction.EXPENSE_CREATED,
        "expense",
        resource_id=expense.id,
        metadata={"category": expense.category, "amount": str(expense.amount)},
    )
    return result


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


@router.post("/expenses/stock-purchase", response_model=StockPurchaseResponse, status_code=201)
async def create_stock_purchase(
    data: StockPurchaseCreate, db: DBSession, current_user: RequireFinanceWrite
) -> StockPurchaseResponse:
    """Book a stock purchase: one expense + one inventory RECEIPT in a single
    atomic commit (the finance ↔ inventory purchase seam)."""
    expense, movement = await FinanceService(db).create_stock_purchase(
        data, actor_id=current_user.id
    )
    result = StockPurchaseResponse(
        expense=ExpenseResponse.model_validate(expense),
        product_id=data.product_id,
        movement_id=movement.id,
        quantity=movement.quantity,
        balance_after=movement.balance_after,
    )
    await AuditService(db).record_user_action_safe(
        current_user,
        AuditAction.EXPENSE_CREATED,
        "expense",
        resource_id=expense.id,
        metadata={
            "category": expense.category,
            "amount": str(expense.amount),
            "product_id": str(data.product_id),
            "stock_movement_id": str(movement.id),
        },
    )
    return result


@router.get("/invoices/{invoice_id}/cogs", response_model=InvoiceCogsResponse)
async def invoice_cogs(
    invoice_id: uuid.UUID, db: DBSession, _: RequireFinanceRead
) -> InvoiceCogsResponse:
    """Cost of goods sold for an invoice's tracked sales — read from inventory's
    weighted-average cost (finance → inventory read seam)."""
    cogs = await FinanceService(db).cogs_for_invoice(invoice_id)
    return InvoiceCogsResponse(invoice_id=invoice_id, cogs=cogs)


# ── Accounts payable (approval workflow) ──────────────────────────────────────


@router.get("/payables/queue", response_model=PayableQueueResponse)
async def payable_queue(
    db: DBSession,
    _: RequireFinanceRead,
    limit: int = Query(default=100, le=500),
) -> PayableQueueResponse:
    """In-flight payables (pending/approved/scheduled) + KPIs for the AP queue."""
    return await FinanceService(db).list_payable_queue(limit=limit)


@router.post("/payables", response_model=PayableResponse, status_code=201)
async def create_payable(
    data: PayableCreate, db: DBSession, current_user: RequireFinanceWrite
) -> PayableResponse:
    """Submit a bill into the AP queue (lands at PENDING_REVIEW, no budget burn)."""
    expense = await FinanceService(db).create_payable(data, current_user)
    result = PayableResponse.model_validate(expense)
    await AuditService(db).record_user_action_safe(
        current_user,
        AuditAction.PAYABLE_SUBMITTED,
        "payable",
        resource_id=expense.id,
        metadata={"category": expense.category, "amount": str(expense.amount)},
    )
    return result


@router.post("/payables/{payable_id}/approve", response_model=PayableResponse)
async def approve_payable(
    payable_id: uuid.UUID, db: DBSession, current_user: RequireFinanceApprove
) -> PayableResponse:
    """Approve a pending payable (reviewer must differ from submitter)."""
    expense = await FinanceService(db).transition_payable(
        payable_id, current_user, target=ExpenseApprovalStatus.APPROVED
    )
    result = PayableResponse.model_validate(expense)
    await AuditService(db).record_user_action_safe(
        current_user,
        AuditAction.PAYABLE_APPROVED,
        "payable",
        resource_id=expense.id,
        metadata={"amount": str(expense.amount), "submitted_by": str(expense.submitted_by)},
    )
    return result


@router.post("/payables/{payable_id}/reject", response_model=PayableResponse)
async def reject_payable(
    payable_id: uuid.UUID, db: DBSession, current_user: RequireFinanceApprove
) -> PayableResponse:
    """Reject a pending payable (reviewer must differ from submitter)."""
    expense = await FinanceService(db).transition_payable(
        payable_id, current_user, target=ExpenseApprovalStatus.REJECTED
    )
    result = PayableResponse.model_validate(expense)
    await AuditService(db).record_user_action_safe(
        current_user,
        AuditAction.PAYABLE_REJECTED,
        "payable",
        resource_id=expense.id,
        metadata={"amount": str(expense.amount), "submitted_by": str(expense.submitted_by)},
    )
    return result


@router.post("/payables/{payable_id}/schedule", response_model=PayableResponse)
async def schedule_payable(
    payable_id: uuid.UUID,
    db: DBSession,
    current_user: RequireFinanceApprove,
    data: PayableScheduleRequest | None = None,
) -> PayableResponse:
    """Schedule an approved payable for payment."""
    body = data or PayableScheduleRequest()
    expense = await FinanceService(db).transition_payable(
        payable_id,
        current_user,
        target=ExpenseApprovalStatus.SCHEDULED,
        scheduled_for=body.scheduled_for,
    )
    result = PayableResponse.model_validate(expense)
    await AuditService(db).record_user_action_safe(
        current_user,
        AuditAction.PAYABLE_SCHEDULED,
        "payable",
        resource_id=expense.id,
        metadata={
            "scheduled_for": expense.scheduled_for.isoformat() if expense.scheduled_for else None
        },
    )
    return result


# ── M-Pesa ────────────────────────────────────────────────────────────────────


@router.post(
    "/mpesa/callback",
    status_code=200,
    dependencies=[Depends(verify_mpesa_signature)],
)
async def mpesa_callback(payload: MpesaCallbackPayload, db: DBSession) -> dict[str, Any]:
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
    result = PaymentResponse.model_validate(payment)
    await AuditService(db).record_user_action_safe(
        current_user,
        AuditAction.PAYMENT_RECORDED,
        "payment",
        resource_id=payment.id,
        metadata={
            "invoice_id": str(payment.invoice_id),
            "amount": str(payment.amount),
            "vault": payment.vault.value,
        },
    )
    return result


# ── Budgets ───────────────────────────────────────────────────────────────────


@router.post("/budgets", response_model=BudgetResponse, status_code=201)
async def create_budget(
    data: BudgetCreate, db: DBSession, current_user: RequireFinanceWrite
) -> BudgetResponse:
    budget = await FinanceService(db).create_budget(data)
    result = BudgetResponse.model_validate(budget)
    await AuditService(db).record_user_action_safe(
        current_user,
        AuditAction.BUDGET_CREATED,
        "budget",
        resource_id=budget.id,
        metadata={
            "name": budget.name,
            "category": budget.category,
            "amount": str(budget.amount),
            "currency": budget.currency,
        },
    )
    return result


@router.get("/budgets", response_model=list[BudgetResponse])
async def list_budgets(db: DBSession, _: RequireFinanceRead) -> list[BudgetResponse]:
    budgets = await FinanceService(db).list_budgets()
    return [BudgetResponse.model_validate(b) for b in budgets]
