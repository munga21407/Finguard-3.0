import uuid
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

import structlog
from pydantic import ValidationError
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.core.exceptions import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    UnprocessableError,
)
from src.domains.crm.models import Customer
from src.domains.finance.events import (
    SNAPSHOT_INTERVAL,
    InvoiceState,
    fold_from_snapshot,
    fold_invoice_events,
)
from src.domains.finance.models import (
    BANK_REVIEW_APPROVED,
    BANK_REVIEW_PENDING,
    BANK_REVIEW_REJECTED,
    BankStatementLine,
    Budget,
    Expense,
    ExpenseApprovalStatus,
    Invoice,
    InvoiceEvent,
    InvoiceEventType,
    InvoiceSnapshot,
    InvoiceStatus,
    LedgerEntry,
    MpesaTransaction,
    OutboxEvent,
    Payment,
    VaultTransfer,
)
from src.domains.finance.reports import (
    build_cash_flow,
    build_income_statement,
    build_tax_liability,
)
from src.domains.finance.repository import (
    BankStatementRepository,
    BudgetRepository,
    ExpenseRepository,
    InvoiceEventRepository,
    InvoiceRepository,
    InvoiceSnapshotRepository,
    LedgerRepository,
    MpesaRepository,
    PaymentRepository,
    VaultTransferRepository,
)
from src.domains.finance.schemas import (
    BankStatementLineImport,
    BudgetCreate,
    ExpenseCreate,
    FinancialReport,
    InvoiceCreate,
    InvoiceUpdate,
    LedgerEntryCreate,
    MpesaCallbackPayload,
    MpesaStkCallback,
    MpesaTransactionResponse,
    PayableCreate,
    PayableQueueKpis,
    PayableQueueResponse,
    PayableResponse,
    PaymentCreate,
    ReceiptExpenseCreate,
    ReconciliationFlowResponse,
    ReportCatalogItem,
    ReportCatalogResponse,
    ReportType,
    SankeyLink,
    SankeyNode,
    StockPurchaseCreate,
    VaultBalance,
    VaultBalancesResponse,
    VaultTransferCreate,
)
from src.domains.finance.types import VaultType
from src.domains.identity.models import User
from src.domains.identity.permissions import Permission

# finance → inventory is a permitted one-way dependency (see the domain-boundary
# test): finance composes inventory writes; inventory never imports finance.
from src.domains.inventory.models import StockMovement
from src.domains.inventory.service import InventoryService
from src.domains.notifications.models import EmailCategory
from src.domains.notifications.reviewers import notify_reviewers
from src.domains.notifications.service import NotificationService

logger = structlog.get_logger(__name__)


class FinanceService:
    def __init__(self, session: AsyncSession) -> None:
        self._ledger_repo = LedgerRepository(session)
        self._invoice_repo = InvoiceRepository(session)
        self._budget_repo = BudgetRepository(session)
        self._expense_repo = ExpenseRepository(session)
        self._mpesa_repo = MpesaRepository(session)
        self._payment_repo = PaymentRepository(session)
        self._invoice_event_repo = InvoiceEventRepository(session)
        self._invoice_snapshot_repo = InvoiceSnapshotRepository(session)
        self._bank_repo = BankStatementRepository(session)
        self._vault_transfer_repo = VaultTransferRepository(session)
        self._session = session

    async def post_ledger_entry(self, data: LedgerEntryCreate) -> LedgerEntry:
        entry = LedgerEntry(**data.model_dump())
        entry = await self._ledger_repo.create(entry)
        await self._session.commit()
        return entry

    async def create_invoice(self, data: InvoiceCreate) -> Invoice:
        if await self._invoice_repo.get_by_number(data.invoice_number):
            raise ConflictError(f"Invoice {data.invoice_number} already exists")
        total = data.subtotal + data.tax
        invoice = Invoice(
            **data.model_dump(), total=total, amount_paid=Decimal("0"), balance_due=total
        )
        invoice = await self._invoice_repo.create(invoice)
        # Event sourcing: issuance is the first event in the invoice's append-only
        # log.  The materialized row above is the projection of this single event;
        # every later payment appends to the log and re-projects (see
        # record_cash_payment / _project_invoice_from_events).
        await self._invoice_event_repo.append(
            InvoiceEvent(
                invoice_id=invoice.id,
                sequence=1,
                event_type=InvoiceEventType.INVOICE_ISSUED,
                amount=total,
                payload={
                    "invoice_number": invoice.invoice_number,
                    "subtotal": float(data.subtotal),
                    "tax": float(data.tax),
                    "currency": invoice.currency,
                },
                occurred_at=invoice.created_at,
            )
        )
        self._session.add(
            OutboxEvent(
                exchange="finguard.finance",
                routing_key="finance.invoice.created",
                payload={"invoice_id": str(invoice.id), "customer_id": str(invoice.customer_id)},
            )
        )
        await self._session.commit()
        return invoice

    async def send_invoice(self, invoice_id: uuid.UUID, current_user: User) -> Invoice:
        """Issue a draft invoice: flip DRAFT → SENT and email it to the customer.

        Only a DRAFT invoice can be sent — a partially-paid, paid, or cancelled
        invoice has already progressed past issuance. ``SENT`` is a manual status
        the event fold leaves intact. The email is enqueued in the same
        transaction (idempotent on the invoice), so the status flip and delivery
        are atomic; a customer without an email still flips status (skip send).
        """
        invoice = await self._invoice_repo.get_by_id_for_update(invoice_id)
        if not invoice:
            raise NotFoundError("Invoice not found")
        if invoice.status != InvoiceStatus.DRAFT:
            raise UnprocessableError(
                f"Only a draft invoice can be sent (this one is {invoice.status})"
            )

        invoice.status = InvoiceStatus.SENT
        invoice = await self._invoice_repo.save(invoice)

        customer = await self._session.get(Customer, invoice.customer_id)
        await NotificationService(self._session).enqueue_email(
            to_email=customer.email if customer else None,
            to_name=customer.name if customer else None,
            subject=f"Invoice {invoice.invoice_number}",
            template="invoice_issued",
            context={
                "customer_name": customer.name if customer else None,
                "invoice_number": invoice.invoice_number,
                "currency": invoice.currency,
                "total": str(invoice.total),
                "balance_due": str(invoice.balance_due),
                "due_date": invoice.due_date.date().isoformat() if invoice.due_date else None,
            },
            idempotency_key=f"invoice_sent:{invoice.id}",
            category=EmailCategory.INVOICE,
        )
        await self._session.commit()
        return invoice

    async def resend_invoice(self, invoice_id: uuid.UUID, current_user: User) -> Invoice:
        """Re-email an already-issued invoice (fresh idempotency key, always sends).

        Unlike :meth:`send_invoice` this does not change status — it's for an
        invoice the customer says they never received. A draft (not yet sent) or a
        cancelled invoice cannot be resent.
        """
        invoice = await self._invoice_repo.get_by_id(invoice_id)
        if not invoice:
            raise NotFoundError("Invoice not found")
        if invoice.status in (InvoiceStatus.DRAFT, InvoiceStatus.CANCELLED):
            raise UnprocessableError(
                f"Only an issued invoice can be resent (this one is {invoice.status})"
            )
        customer = await self._session.get(Customer, invoice.customer_id)
        await NotificationService(self._session).enqueue_email(
            to_email=customer.email if customer else None,
            to_name=customer.name if customer else None,
            subject=f"Invoice {invoice.invoice_number}",
            template="invoice_issued",
            context={
                "customer_name": customer.name if customer else None,
                "invoice_number": invoice.invoice_number,
                "currency": invoice.currency,
                "total": str(invoice.total),
                "balance_due": str(invoice.balance_due),
                "due_date": invoice.due_date.date().isoformat() if invoice.due_date else None,
            },
            # Fresh key every resend so it always delivers (not deduped).
            idempotency_key=f"invoice_resent:{invoice.id}:{uuid.uuid4()}",
            category=EmailCategory.INVOICE,
        )
        await self._session.commit()
        return invoice

    async def _project_invoice_from_events(self, invoice: Invoice) -> InvoiceState:
        """Re-derive an invoice's monetary fields from its event log.

        Resumes the fold from the latest snapshot (replaying only the events
        after it) and applies the result to the materialized ``invoices`` row
        in-place (caller owns the commit).  ``amount_paid`` and ``balance_due``
        are always overwritten so the row provably equals the fold;
        ``status``/``paid_at`` are only touched when the fold owns the status (a
        payment/credit/cancel has been applied) — manual statuses
        (DRAFT/SENT/OVERDUE) are left intact.  This is the synchronous projection;
        moving it onto the outbox consumer is a documented follow-up.
        """
        snapshot = await self._invoice_snapshot_repo.latest(invoice.id)
        if snapshot is None:
            events = await self._invoice_event_repo.list_by_invoice(invoice.id)
            state = fold_invoice_events(events)
        else:
            base = InvoiceState.from_snapshot(snapshot.state)
            tail = await self._invoice_event_repo.list_after_sequence(
                invoice.id, snapshot.sequence
            )
            state = fold_from_snapshot(base, tail)

        invoice.amount_paid = state.amount_paid
        invoice.amount_credited = state.credited
        invoice.balance_due = state.balance_due
        if state.payment_status is not None:
            invoice.status = state.payment_status
            invoice.paid_at = state.paid_at

        await self._maybe_snapshot(invoice.id, state)
        return state

    async def _maybe_snapshot(self, invoice_id: uuid.UUID, state: InvoiceState) -> None:
        """Persist a fresh snapshot once the log crosses a ``SNAPSHOT_INTERVAL`` boundary.

        Caps replay cost: the next projection folds at most ``SNAPSHOT_INTERVAL``
        tail events.  A snapshot is a pure cache — skipping it only makes the next
        replay longer, never wrong — so we no-op if one already exists at this
        sequence (the ``(invoice_id, sequence)`` uniqueness would otherwise clash).
        """
        if state.event_count == 0 or state.event_count % SNAPSHOT_INTERVAL != 0:
            return
        latest = await self._invoice_snapshot_repo.latest(invoice_id)
        if latest is not None and latest.sequence >= state.sequence:
            return
        await self._invoice_snapshot_repo.create(
            InvoiceSnapshot(
                invoice_id=invoice_id,
                sequence=state.sequence,
                state=state.to_snapshot(),
            )
        )

    async def update_invoice(self, invoice_id: uuid.UUID, data: InvoiceUpdate) -> Invoice:
        invoice = await self._invoice_repo.get_by_id(invoice_id)
        if not invoice:
            raise NotFoundError("Invoice not found")
        for field, value in data.model_dump(exclude_none=True).items():
            setattr(invoice, field, value)
        invoice = await self._invoice_repo.save(invoice)
        await self._session.commit()
        return invoice

    async def mark_invoice_paid(
        self,
        invoice_id: uuid.UUID,
        current_user: User | None = None,
        vault: VaultType = VaultType.CASH,
        reference_note: str | None = None,
    ) -> Invoice:
        invoice = await self._invoice_repo.get_by_id_for_update(invoice_id)
        if not invoice:
            raise NotFoundError("Invoice not found")
        # Settle by recording a Payment for the outstanding balance on the chosen
        # rail (``vault``) and appending the matching payment_applied event, then
        # re-projecting — so the event log stays the single source of truth, the
        # row never drifts from ck_invoices_balance_due_consistent, AND every
        # shilling of amount_paid is backed by a Payment row (which keeps the
        # reconciliation Sankey free of an "unlinked" rail and lands the cash in the
        # right vault). A no-op when the invoice is already fully settled.
        remaining = invoice.balance_due
        if remaining > Decimal("0"):
            now = datetime.now(UTC)
            recorded_by = current_user.id if current_user else None
            payment = await self._payment_repo.create(
                Payment(
                    invoice_id=invoice.id,
                    amount=remaining,
                    vault=vault,
                    reference_note=reference_note or "Manual settlement",
                    payment_date=now,
                    recorded_by=recorded_by,
                )
            )
            sequence = await self._invoice_event_repo.next_sequence(invoice.id)
            await self._invoice_event_repo.append(
                InvoiceEvent(
                    invoice_id=invoice.id,
                    sequence=sequence,
                    event_type=InvoiceEventType.PAYMENT_APPLIED,
                    amount=remaining,
                    payload={
                        "reason": "manual_settlement",
                        "payment_id": str(payment.id),
                        "vault": vault.value,
                    },
                    occurred_at=now,
                    recorded_by=recorded_by,
                )
            )
            await self._project_invoice_from_events(invoice)
        invoice = await self._invoice_repo.save(invoice)
        await self._session.commit()
        return invoice

    async def apply_credit_note(
        self,
        invoice_id: uuid.UUID,
        amount: Decimal,
        current_user: User | None = None,
        reason: str | None = None,
    ) -> Invoice:
        """Reduce an invoice's receivable by a credit note (event-sourced).

        Appends a ``credit_note_applied`` event and re-projects, so the credit
        flows through the same fold as payments — ``balance_due`` becomes
        ``total - credited - amount_paid``.  Holds the invoice ``FOR UPDATE`` so a
        concurrent payment/credit cannot allocate the same ``sequence``.  Guards:
        a cancelled invoice cannot be credited, and the credit cannot exceed the
        current outstanding balance (no negative balance / over-credit).
        """
        if amount <= Decimal("0"):
            raise UnprocessableError("Credit note amount must be positive")
        invoice = await self._invoice_repo.get_by_id_for_update(invoice_id)
        if not invoice:
            raise NotFoundError("Invoice not found")
        if invoice.status == InvoiceStatus.CANCELLED:
            raise UnprocessableError("Cannot credit a cancelled invoice")
        if amount > invoice.balance_due:
            raise UnprocessableError(
                "Credit note exceeds the invoice's outstanding balance"
            )
        now = datetime.now(UTC)
        recorded_by = current_user.id if current_user else None
        sequence = await self._invoice_event_repo.next_sequence(invoice.id)
        await self._invoice_event_repo.append(
            InvoiceEvent(
                invoice_id=invoice.id,
                sequence=sequence,
                event_type=InvoiceEventType.CREDIT_NOTE_APPLIED,
                amount=amount,
                payload={"reason": reason or "credit_note"},
                occurred_at=now,
                recorded_by=recorded_by,
            )
        )
        await self._project_invoice_from_events(invoice)
        invoice = await self._invoice_repo.save(invoice)
        await self._session.commit()
        return invoice

    async def cancel_invoice(
        self,
        invoice_id: uuid.UUID,
        current_user: User | None = None,
        reason: str | None = None,
    ) -> Invoice:
        """Void an invoice (terminal, event-sourced).

        Appends an ``invoice_cancelled`` event and re-projects; the fold derives
        status ``CANCELLED`` and stops accruing monetary state.  A paid or
        already-cancelled invoice cannot be cancelled — cancellation is for
        receivables that will never be collected, not for reversing settled cash
        (use a credit note / refund flow for that).
        """
        invoice = await self._invoice_repo.get_by_id_for_update(invoice_id)
        if not invoice:
            raise NotFoundError("Invoice not found")
        if invoice.status == InvoiceStatus.CANCELLED:
            raise UnprocessableError("Invoice is already cancelled")
        if invoice.status == InvoiceStatus.PAID:
            raise UnprocessableError("Cannot cancel a fully-paid invoice")
        now = datetime.now(UTC)
        recorded_by = current_user.id if current_user else None
        sequence = await self._invoice_event_repo.next_sequence(invoice.id)
        await self._invoice_event_repo.append(
            InvoiceEvent(
                invoice_id=invoice.id,
                sequence=sequence,
                event_type=InvoiceEventType.INVOICE_CANCELLED,
                amount=Decimal("0"),
                payload={"reason": reason or "cancelled"},
                occurred_at=now,
                recorded_by=recorded_by,
            )
        )
        await self._project_invoice_from_events(invoice)
        invoice = await self._invoice_repo.save(invoice)
        await self._session.commit()
        return invoice

    # ── Expenses ──────────────────────────────────────────────────────────────

    async def create_expense(self, data: ExpenseCreate) -> Expense:
        expense = Expense(**data.model_dump())
        expense = await self._expense_repo.create(expense)
        await self._apply_expense_side_effects(expense, source="database.expenses")
        await self._session.commit()
        return expense

    async def create_receipt_expense(self, data: ReceiptExpenseCreate) -> Expense:
        """Persist an expense from a reviewed receipt scan.

        Same transactional guarantees as ``create_expense`` (budget burn-down +
        outbox event in one transaction), but additionally stores the OCR audit
        trail (merchant, KRA PIN, printed date, note).  The ``expenses.created``
        event still fires, so Agent E's watchdog evaluates receipt expenses
        exactly like API-created ones.
        """
        expense = Expense(
            expense_ref=data.expense_ref,
            customer_id=data.customer_id,
            category=data.category,
            amount=data.amount,
            vault=data.vault,
            merchant_name=data.merchant_name,
            kra_pin=data.kra_pin,
            description=data.description,
            receipt_date=data.receipt_date,
        )
        expense = await self._expense_repo.create(expense)
        await self._apply_expense_side_effects(expense, source="receipt.scan")
        await self._session.commit()
        return expense

    async def create_stock_purchase(
        self, data: StockPurchaseCreate, *, actor_id: uuid.UUID | None = None
    ) -> tuple[Expense, StockMovement]:
        """Book an expense and receive the purchased stock in **one** commit, so a
        crash can never leave stock received without its expense (or vice versa).

        Cross-domain call goes finance → inventory (never the reverse): inventory
        stores the ``reference=(expense, id)`` link; finance holds no product FK.
        """
        expense = Expense(**data.expense.model_dump())
        expense = await self._expense_repo.create(expense)
        await self._apply_expense_side_effects(expense, source="inventory.purchase")
        inventory = InventoryService(self._session)
        movement = await inventory.record_purchase_receipt(
            data.product_id,
            data.quantity,
            data.unit_cost,
            reference_id=expense.id,
            actor_id=actor_id,
        )
        await self._session.commit()
        # A restock can clear a standing low-stock alert (best-effort, post-commit).
        await inventory.reconcile_low_stock_alert(data.product_id)
        return expense, movement

    async def cogs_for_invoice(self, invoice_id: uuid.UUID) -> Decimal:
        """Gross-margin input: cost of goods sold for a sale, read from inventory's
        weighted-average cost (finance → inventory read seam)."""
        return await InventoryService(self._session).cogs_for_invoice(invoice_id)

    async def _apply_expense_side_effects(self, expense: Expense, *, source: str) -> None:
        """Budget burn-down + outbox event for a freshly-flushed expense.

        Shared by ``create_expense`` and ``create_receipt_expense``.  Does NOT
        commit — the caller owns the transaction boundary so the expense INSERT,
        budget UPDATE, and outbox INSERT all succeed or fail together.
        """
        # Increment the spent counter on every budget whose category and active
        # period match this expense, so Agent E's watchdog always reads a
        # consistent burn rate.  No matching budget → safe no-op (0 rows).
        await self._session.execute(
            text("""
                UPDATE budgets
                SET spent = spent + :amount
                WHERE category   = :category
                  AND period_start <= :now
                  AND period_end   >= :now
            """),
            {
                "amount":   expense.amount,
                "category": expense.category,
                "now":      datetime.now(UTC),
            },
        )

        # Emit via the transactional outbox so a broker outage cannot silently
        # drop the event while the database row persists — the projector
        # delivers it with at-least-once semantics.
        self._session.add(
            OutboxEvent(
                exchange="finguard.events",
                routing_key="expenses.created",
                payload={
                    "event_name": "expenses.created",
                    "emitted_at": datetime.now(UTC).isoformat(),
                    "payload": {
                        "expense_id": str(expense.id),
                        "amount": float(expense.amount),
                        "category": expense.category,
                        "vault": expense.vault.value,
                        "occurred_at": expense.created_at.isoformat(),
                        "source": source,
                    },
                },
            )
        )

    async def list_expenses(self, limit: int = 100, offset: int = 0) -> list[Expense]:
        return await self._expense_repo.list_all(limit=limit, offset=offset)

    # ── Accounts payable (approval workflow) ───────────────────────────────────

    # Legal approval-status edges.  A payable is submitted straight into review;
    # a reviewer (≠ submitter) approves or rejects it, and an approved bill can be
    # scheduled for payment.  Anything not listed here is rejected by
    # ``transition_payable`` (e.g. re-approving, reviving a rejected bill).
    _PAYABLE_TRANSITIONS: dict[ExpenseApprovalStatus, frozenset[ExpenseApprovalStatus]] = {
        ExpenseApprovalStatus.DRAFT: frozenset({ExpenseApprovalStatus.PENDING_REVIEW}),
        ExpenseApprovalStatus.PENDING_REVIEW: frozenset(
            {ExpenseApprovalStatus.APPROVED, ExpenseApprovalStatus.REJECTED}
        ),
        ExpenseApprovalStatus.APPROVED: frozenset({ExpenseApprovalStatus.SCHEDULED}),
    }
    _REVIEW_DECISIONS = frozenset(
        {ExpenseApprovalStatus.APPROVED, ExpenseApprovalStatus.REJECTED}
    )

    async def create_payable(self, data: PayableCreate, current_user: User) -> Expense:
        """Submit a bill into the AP queue at PENDING_REVIEW.

        Deliberately applies NO side effects: a payable awaiting review must not
        burn budget or emit the ``expenses.created`` watchdog event until a
        reviewer approves it (see ``transition_payable``).
        """
        expense = Expense(
            expense_ref=data.expense_ref,
            customer_id=data.customer_id,
            category=data.category,
            amount=data.amount,
            vault=data.vault,
            description=data.description,
            merchant_name=data.merchant_name,
            approval_status=ExpenseApprovalStatus.PENDING_REVIEW,
            submitted_by=current_user.id,
        )
        expense = await self._expense_repo.create(expense)
        # Notify everyone who can sign this off (finance:approve), except the
        # submitter — they can't review their own bill. Enqueue-only (atomic with
        # the payable).
        await notify_reviewers(
            self._session,
            permission=Permission.FINANCE_APPROVE,
            subject="A payable needs your approval",
            template="approval_needed",
            context={
                "summary": f"A bill of {expense.amount} ({expense.category}) is awaiting approval.",
                "detail": expense.description or expense.merchant_name or "",
                "review_url": f"{settings.APP_BASE_URL}/dashboard/approvals",
            },
            resource_id=expense.id,
            key_prefix="payable_review",
            exclude_user_id=current_user.id,
        )
        await self._session.commit()
        return expense

    async def transition_payable(
        self,
        expense_id: uuid.UUID,
        current_user: User,
        *,
        target: ExpenseApprovalStatus,
        scheduled_for: datetime | None = None,
    ) -> Expense:
        """Move a payable along its approval state machine (maker-checker).

        Enforces the legal edges in ``_PAYABLE_TRANSITIONS`` and segregation of
        duties — the submitter cannot review (approve/reject) their own payable,
        mirroring the bank-statement review gate.  The expense is held
        ``FOR UPDATE`` so two reviewers cannot both approve it and double-burn the
        budget.  Budget burn-down + the watchdog event are applied exactly once,
        on the transition into APPROVED.
        """
        expense = await self._expense_repo.get_by_id_for_update(expense_id)
        if not expense:
            raise NotFoundError("Payable not found")

        allowed = self._PAYABLE_TRANSITIONS.get(expense.approval_status, frozenset())
        if target not in allowed:
            raise UnprocessableError(
                f"Cannot move payable from {expense.approval_status} to {target}"
            )
        if target in self._REVIEW_DECISIONS and expense.submitted_by == current_user.id:
            raise ForbiddenError("The submitter cannot review their own payable")

        now = datetime.now(UTC)
        expense.approval_status = target
        if target in self._REVIEW_DECISIONS:
            expense.reviewed_by = current_user.id
            expense.reviewed_at = now
        if target == ExpenseApprovalStatus.APPROVED:
            # Deferred side effects fire now, once, as the bill is signed off.
            await self._apply_expense_side_effects(expense, source="payable.approved")
        if target == ExpenseApprovalStatus.SCHEDULED:
            expense.scheduled_for = scheduled_for or now

        await self._session.commit()
        await self._session.refresh(expense)
        return expense

    async def list_payable_queue(self, limit: int = 100) -> PayableQueueResponse:
        """In-flight payables (pending + approved) plus summary KPIs for the page."""
        items = await self._expense_repo.list_by_approval_statuses(
            (
                ExpenseApprovalStatus.PENDING_REVIEW,
                ExpenseApprovalStatus.APPROVED,
                ExpenseApprovalStatus.SCHEDULED,
            ),
            limit=limit,
        )
        aggregates = await self._expense_repo.approval_status_aggregates()
        pending = aggregates.get(ExpenseApprovalStatus.PENDING_REVIEW, (0, Decimal("0")))
        approved = aggregates.get(ExpenseApprovalStatus.APPROVED, (0, Decimal("0")))
        scheduled = aggregates.get(ExpenseApprovalStatus.SCHEDULED, (0, Decimal("0")))
        return PayableQueueResponse(
            kpis=PayableQueueKpis(
                pending_count=pending[0],
                pending_amount=pending[1],
                approved_count=approved[0],
                approved_amount=approved[1],
                scheduled_count=scheduled[0],
            ),
            items=[PayableResponse.model_validate(e) for e in items],
        )

    # ── M-Pesa ────────────────────────────────────────────────────────────────

    async def process_mpesa_callback(
        self, payload: MpesaCallbackPayload
    ) -> MpesaTransactionResponse | None:
        """
        Parse a Daraja STK Push callback, persist the transaction, and enqueue
        an ``mpesa.reconciled`` event via the transactional outbox.

        Returns:
            MpesaTransactionResponse — on a successful, fully-formed callback
                (or the existing record when the receipt was already processed).
            None — when the callback reports a failed payment (ResultCode != 0).

        Raises:
            UnprocessableError — when the envelope is malformed, or a *success*
                callback is missing the receipt number, amount, or phone.  The
                caller (router) ACKs Daraja regardless; we never persist a
                transaction with blank identifiers or a zero amount.
        """
        # ── 1. Validate the envelope shape with the strict schema ────────────
        stk_raw = payload.Body.get("stkCallback")
        if not isinstance(stk_raw, dict):
            raise UnprocessableError("Malformed M-Pesa callback: missing 'stkCallback' object")
        try:
            stk = MpesaStkCallback.model_validate(stk_raw)
        except ValidationError as exc:
            raise UnprocessableError(
                f"Malformed M-Pesa stkCallback: {exc.error_count()} validation error(s)"
            ) from exc

        # ── 2. Non-success callbacks: nothing to persist ─────────────────────
        if stk.ResultCode != 0:
            logger.info(
                "mpesa: non-success callback ignored",
                result_code=stk.ResultCode,
                checkout_request_id=stk.CheckoutRequestID,
            )
            return None

        # ── 3. Require the metadata a real successful payment always carries ──
        items: dict[str, str | int | float | None] = {
            item.Name: item.Value
            for item in (stk.CallbackMetadata.Item if stk.CallbackMetadata else [])
        }
        receipt = items.get("MpesaReceiptNumber")
        amount_raw = items.get("Amount")
        phone_raw = items.get("PhoneNumber")
        if not receipt or amount_raw is None or not phone_raw:
            raise UnprocessableError(
                "Successful M-Pesa callback missing required metadata "
                "(MpesaReceiptNumber, Amount, or PhoneNumber)"
            )
        try:
            amount = Decimal(str(amount_raw))
        except (InvalidOperation, ValueError) as exc:
            raise UnprocessableError(
                f"M-Pesa callback has non-numeric Amount: {amount_raw!r}"
            ) from exc
        if amount <= 0:
            raise UnprocessableError(f"M-Pesa callback Amount must be positive, got {amount}")

        trans_id = str(receipt)
        phone = str(phone_raw)
        bill_ref = stk.CheckoutRequestID

        # ── 4. Idempotent: skip if this receipt was already recorded ─────────
        existing = await self._mpesa_repo.get_by_trans_id(trans_id)
        if existing:
            logger.info("mpesa: duplicate callback ignored", trans_id=trans_id)
            return MpesaTransactionResponse.model_validate(existing)

        # ── 5. Persist transaction + outbox event in one transaction ─────────
        txn = MpesaTransaction(
            trans_id=trans_id,
            amount=amount,
            phone=phone,
            bill_ref=bill_ref,
            vault=VaultType.MPESA,
            raw_payload=payload.Body,  # retained for audit / dispute resolution
        )
        txn = await self._mpesa_repo.create(txn)
        self._session.add(
            OutboxEvent(
                exchange="finguard.events",
                routing_key="mpesa.reconciled",
                payload={
                    "event_name": "mpesa.reconciled",
                    "emitted_at": datetime.now(UTC).isoformat(),
                    "payload": {
                        "trans_id": txn.trans_id,
                        "amount": float(txn.amount),
                        "phone": txn.phone,
                        "bill_ref": txn.bill_ref,
                        "vault": txn.vault.value,
                    },
                },
            )
        )
        await self._session.commit()
        return MpesaTransactionResponse.model_validate(txn)

    # ── Invoices (extra reads) ─────────────────────────────────────────────────

    async def list_invoices(self, customer_id: uuid.UUID | None = None) -> list[Invoice]:
        if customer_id:
            return await self._invoice_repo.list_by_customer(customer_id)
        result = await self._session.execute(
            select(Invoice).order_by(Invoice.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_invoice(self, invoice_id: uuid.UUID) -> Invoice:
        invoice = await self._invoice_repo.get_by_id(invoice_id)
        if not invoice:
            raise NotFoundError("Invoice not found")
        return invoice

    async def get_invoice_events(self, invoice_id: uuid.UUID) -> list[InvoiceEvent]:
        """Return an invoice's append-only event history (oldest first)."""
        invoice = await self._invoice_repo.get_by_id(invoice_id)
        if not invoice:
            raise NotFoundError("Invoice not found")
        return await self._invoice_event_repo.list_by_invoice(invoice_id)

    async def reconstruct_invoice(
        self, invoice_id: uuid.UUID
    ) -> tuple[Invoice, InvoiceState, list[InvoiceEvent]]:
        """Fold an invoice's events into derived state for audit verification.

        Returns the materialized invoice, the state derived purely from its event
        log, and the events themselves — letting a caller assert the stored row
        equals the fold (i.e. the projection has not drifted from the source of
        truth).
        """
        invoice = await self._invoice_repo.get_by_id(invoice_id)
        if not invoice:
            raise NotFoundError("Invoice not found")
        events = await self._invoice_event_repo.list_by_invoice(invoice_id)
        state = fold_invoice_events(events)
        return invoice, state, events

    async def get_reconciliation_flow(self) -> ReconciliationFlowResponse:
        """Build the invoice-lifecycle → settlement-rail Sankey for the Overview.

        Stage 1 (Total Billed) → Stage 2 (current invoice status, the projection
        of the append-only ``invoice_events`` fold) → Stage 3 (settlement rail).

        Both stages are exact.  Stage 2 → 3 reads ``Payment`` rows grouped by their
        invoice's status and their rail (vault), so each collected shilling flows
        to the rail it actually settled on — M-Pesa / Bank (the reconciled rails,
        produced by Agent C) or Cash.  Every settlement path (cash, reconciliation,
        manual settlement) creates a Payment, so the rails fully account for each
        status's collected total.
        """
        status_rows = await self._invoice_repo.status_aggregates()
        rail_rows = await self._payment_repo.rail_aggregates()

        billed_by_status = {status: total for status, total, _ in status_rows}
        collected_by_status = {status: paid for status, _, paid in status_rows}

        total_billed = sum(billed_by_status.values(), Decimal("0"))
        total_collected = sum(collected_by_status.values(), Decimal("0"))

        # Nothing billed → empty diagram (the frontend renders an honest empty state).
        if total_billed <= 0:
            return ReconciliationFlowResponse(
                nodes=[],
                links=[],
                currency="KES",
                total_billed=Decimal("0"),
                total_collected=Decimal("0"),
                reconciled_total=Decimal("0"),
            )

        nodes: list[SankeyNode] = []
        node_index: dict[str, int] = {}

        def node(name: str, kind: str) -> int:
            if name not in node_index:
                node_index[name] = len(nodes)
                nodes.append(SankeyNode(name=name, kind=kind))
            return node_index[name]

        def money(value: Decimal) -> Decimal:
            return value.quantize(Decimal("0.01"))

        links: list[SankeyLink] = []

        # ── Stage 1 → 2: Total Billed split by current status ─────────────────
        # Lifecycle order so the column reads draft → … → paid top-to-bottom.
        status_labels = {
            InvoiceStatus.DRAFT: "Draft",
            InvoiceStatus.SENT: "Sent",
            InvoiceStatus.OVERDUE: "Overdue",
            InvoiceStatus.PARTIALLY_PAID: "Partially Paid",
            InvoiceStatus.PAID: "Paid",
        }
        source_idx = node("Total Billed", "source")
        for status, label in status_labels.items():
            amount = billed_by_status.get(status, Decimal("0"))
            if amount > 0:
                links.append(
                    SankeyLink(source=source_idx, target=node(label, "status"), value=money(amount))
                )

        # ── Stage 2 → 3: exact per-invoice settlement rails from Payment rows ──
        # Each Payment is grouped by its invoice's status and its rail (vault),
        # so every collected shilling flows to the rail it actually settled on —
        # no proportional estimate.  The MPESA/BANK rails are the reconciled ones.
        rail_labels = {
            VaultType.MPESA: "M-Pesa",
            VaultType.BANK: "Bank",
            VaultType.CASH: "Cash",
        }
        rail_by_status: dict[InvoiceStatus, dict[str, Decimal]] = {}
        reconciled_total = Decimal("0")
        for status, vault, amount in rail_rows:
            rail_name = rail_labels.get(vault)
            if rail_name is None or amount <= 0:
                continue
            rail_by_status.setdefault(status, {})
            rail_by_status[status][rail_name] = (
                rail_by_status[status].get(rail_name, Decimal("0")) + amount
            )
            if vault in (VaultType.MPESA, VaultType.BANK):
                reconciled_total += amount

        # Every shilling of amount_paid is backed by a Payment row (cash,
        # reconciliation and manual settlement all create one), so the rails fully
        # account for each status's collected total — there is no "unlinked" rail.
        for status, label in status_labels.items():
            if billed_by_status.get(status, Decimal("0")) <= 0:
                continue
            rails = rail_by_status.get(status, {})
            status_idx = node(label, "status")
            for rail_label, amount in rails.items():
                links.append(
                    SankeyLink(
                        source=status_idx,
                        target=node(rail_label, "rail"),
                        value=money(amount),
                    )
                )

        return ReconciliationFlowResponse(
            nodes=nodes,
            links=links,
            currency="KES",
            total_billed=money(total_billed),
            total_collected=money(total_collected),
            reconciled_total=money(reconciled_total),
        )

    # ── Reconciliation: link settlements to invoices as Payment rows ───────────

    async def apply_reconciled_payment(
        self,
        *,
        invoice_id: uuid.UUID | str,
        amount: Decimal | float,
        vault: VaultType,
        occurred_at: datetime,
        mpesa_trans_id: uuid.UUID | str | None = None,
        bank_line_id: uuid.UUID | str | None = None,
    ) -> Payment | None:
        """Apply a reconciliation match as a first-class Payment, event-sourced.

        Mirrors :meth:`record_cash_payment` (Payment row + ``payment_applied``
        event + re-projection) so a reconciled M-Pesa/bank settlement links to its
        invoice exactly like a manual cash payment — keeping the event log complete
        and ``reconstruct_invoice`` drift-free.  ``recorded_by`` is NULL (no human
        actor) and the source settlement row is marked reconciled.

        Flush-only: the caller (Agent C, inside ``session.begin()``) owns the
        commit/rollback.  Returns ``None`` if the invoice is already fully settled.
        """
        inv_uuid = invoice_id if isinstance(invoice_id, uuid.UUID) else uuid.UUID(str(invoice_id))
        invoice = await self._invoice_repo.get_by_id_for_update(inv_uuid)
        if not invoice:
            raise NotFoundError("Invoice not found")

        # Never over-credit: clamp the applied amount to the outstanding balance so
        # amount_paid ≤ total and balance_due ≥ 0 hold (the cash path errors here;
        # automated reconciliation simply applies what the invoice can absorb).
        applied = min(Decimal(str(amount)), invoice.balance_due)
        if applied <= 0:
            return None

        mpesa_uuid = (
            None if mpesa_trans_id is None
            else mpesa_trans_id if isinstance(mpesa_trans_id, uuid.UUID)
            else uuid.UUID(str(mpesa_trans_id))
        )
        bank_uuid = (
            None if bank_line_id is None
            else bank_line_id if isinstance(bank_line_id, uuid.UUID)
            else uuid.UUID(str(bank_line_id))
        )

        payment = Payment(
            invoice_id=invoice.id,
            amount=applied,
            vault=vault,
            reference_note=f"Auto-reconciled ({vault.value})",
            payment_date=occurred_at,
            recorded_by=None,
            mpesa_trans_id=mpesa_uuid,
            bank_line_id=bank_uuid,
        )
        payment = await self._payment_repo.create(payment)

        sequence = await self._invoice_event_repo.next_sequence(invoice.id)
        await self._invoice_event_repo.append(
            InvoiceEvent(
                invoice_id=invoice.id,
                sequence=sequence,
                event_type=InvoiceEventType.PAYMENT_APPLIED,
                amount=applied,
                payload={
                    "payment_id": str(payment.id),
                    "vault": vault.value,
                    "source": "reconciliation",
                    "mpesa_trans_id": str(mpesa_uuid) if mpesa_uuid else None,
                    "bank_line_id": str(bank_uuid) if bank_uuid else None,
                },
                occurred_at=occurred_at,
                recorded_by=None,
            )
        )
        await self._project_invoice_from_events(invoice)

        # Mark the raw settlement record reconciled (mirrors the old _apply_match).
        if mpesa_uuid is not None:
            await self._session.execute(
                text("UPDATE mpesa_transactions SET is_reconciled = TRUE WHERE id = :id"),
                {"id": mpesa_uuid},
            )
        if bank_uuid is not None:
            await self._session.execute(
                text("UPDATE bank_statement_lines SET is_reconciled = TRUE WHERE id = :id"),
                {"id": bank_uuid},
            )

        self._session.add(
            OutboxEvent(
                exchange="finguard.events",
                routing_key="payments.reconciled",
                payload={
                    "event_name": "payments.reconciled",
                    "emitted_at": datetime.now(UTC).isoformat(),
                    "payload": {
                        "payment_id": str(payment.id),
                        "invoice_id": str(invoice.id),
                        "amount": float(applied),
                        "vault": vault.value,
                        "balance_due_after": float(invoice.balance_due),
                    },
                },
            )
        )

        # Receipt to the customer. Enqueue-only — the caller (Agent C, inside
        # session.begin()) owns the commit, so it's atomic with the reconciliation.
        await self._enqueue_payment_receipt(invoice, payment)

        return payment

    async def import_bank_statement_lines(
        self, lines: list[BankStatementLineImport], current_user: User | None = None
    ) -> list[BankStatementLine]:
        """Ingest bank statement lines (unreconciled) for Agent C to match later.

        Idempotent on the required ``external_ref`` (the bank's line reference): a
        line whose ``external_ref`` is already in the request or already persisted
        is skipped, so re-uploading the same statement cannot create duplicate lines
        — and therefore cannot drive a duplicate reconciliation / double-payment.

        Imported bank data auto-reconciles and marks invoices paid, so the importer
        (``current_user``) is stamped on each line and a ``finance.bank_statement.
        imported`` audit event is emitted.  Returns only the newly-created lines.
        """
        imported_by = current_user.id if current_user else None
        already_persisted = await self._bank_repo.existing_external_refs(
            [ln.external_ref for ln in lines]
        )

        rows: list[BankStatementLine] = []
        seen_in_request: set[str] = set()
        for line in lines:
            ref = line.external_ref
            if ref in already_persisted or ref in seen_in_request:
                continue  # duplicate of an existing or earlier-in-request line
            seen_in_request.add(ref)
            rows.append(
                BankStatementLine(
                    amount=line.amount,
                    date=line.date,
                    reference_text=line.reference_text,
                    external_ref=ref,
                    imported_by=imported_by,
                    is_reconciled=False,
                )
            )

        if not rows:
            return []

        rows = await self._bank_repo.bulk_create(rows)
        # Audit trail: who imported how many settlement lines (and their refs).
        self._session.add(
            OutboxEvent(
                exchange="finguard.events",
                routing_key="finance.bank_statement.imported",
                payload={
                    "event_name": "finance.bank_statement.imported",
                    "emitted_at": datetime.now(UTC).isoformat(),
                    "payload": {
                        "imported_by": str(imported_by) if imported_by else None,
                        "line_count": len(rows),
                        "external_refs": [r.external_ref for r in rows],
                        "total_amount": float(sum((r.amount for r in rows), Decimal("0"))),
                    },
                },
            )
        )
        await self._session.commit()
        return rows

    async def list_bank_statement_lines(
        self, *, review_status: str | None = None, limit: int = 100, offset: int = 0
    ) -> list[BankStatementLine]:
        return await self._bank_repo.list_all(
            review_status=review_status, limit=limit, offset=offset
        )

    async def _review_bank_statement_line(
        self, line_id: uuid.UUID, current_user: User, *, decision: str
    ) -> BankStatementLine:
        """Approve or reject a pending bank line (maker-checker).

        Enforces segregation of duties: the reviewer must differ from the importer,
        and only a still-pending, unreconciled line can be decided.  Approving makes
        the line eligible for the reconciler; rejecting keeps it out permanently.
        """
        line = await self._bank_repo.get_by_id(line_id)
        if not line:
            raise NotFoundError("Bank statement line not found")
        if line.is_reconciled:
            raise UnprocessableError("Line is already reconciled")
        if line.review_status != BANK_REVIEW_PENDING:
            raise UnprocessableError(f"Line is already {line.review_status}")
        if line.imported_by is not None and line.imported_by == current_user.id:
            raise ForbiddenError("The importer cannot review their own bank statement line")

        line.review_status = decision
        line.approved_by = current_user.id
        line.approved_at = datetime.now(UTC)
        await self._session.commit()
        await self._session.refresh(line)
        return line

    async def approve_bank_statement_line(
        self, line_id: uuid.UUID, current_user: User
    ) -> BankStatementLine:
        return await self._review_bank_statement_line(
            line_id, current_user, decision=BANK_REVIEW_APPROVED
        )

    async def reject_bank_statement_line(
        self, line_id: uuid.UUID, current_user: User
    ) -> BankStatementLine:
        return await self._review_bank_statement_line(
            line_id, current_user, decision=BANK_REVIEW_REJECTED
        )

    # ── Vault transfers + balances (treasury) ──────────────────────────────────

    async def create_vault_transfer(
        self, data: VaultTransferCreate, current_user: User
    ) -> VaultTransfer:
        """Record an internal vault-to-vault movement of the business's own money.

        Net-zero to total cash: it shifts ``amount`` from ``from_vault`` to
        ``to_vault``.  An optional ``fee`` is booked as a separate Expense on the
        source vault and linked via ``fee_expense_id`` — it reduces the source vault
        balance and total cash (it is genuine cash out), but it is NOT run through
        ``_apply_expense_side_effects``, so a transfer fee never burns a category
        budget (it is a financing cost, not operational spend).

        Overdraw guard: the transfer is rejected if ``amount + fee`` exceeds the
        current source-vault balance — you cannot move more money than a vault holds.
        A transaction-scoped advisory lock on the source vault serialises concurrent
        transfers so the balance read-then-write cannot race into an overdraw.
        """
        # Serialise concurrent transfers OUT of the same vault (held until commit),
        # so the balance check below cannot be undercut by a parallel transfer.
        await self._session.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:vault))"),
            {"vault": f"vault_transfer:{data.from_vault.value}"},
        )

        # Cannot move more than the source vault currently holds.
        balances = await self.get_vault_balances()
        from_balance = next(
            (b.balance for b in balances.balances if b.vault == data.from_vault),
            Decimal("0"),
        )
        if data.amount + data.fee > from_balance:
            raise UnprocessableError(
                f"Transfer of {data.amount} (+ fee {data.fee}) exceeds the "
                f"{data.from_vault.value} balance of {from_balance}"
            )

        transfer = VaultTransfer(
            from_vault=data.from_vault,
            to_vault=data.to_vault,
            amount=data.amount,
            fee=data.fee,
            reference_note=data.reference_note,
            occurred_at=data.occurred_at,
            recorded_by=current_user.id,
        )
        transfer = await self._vault_transfer_repo.create(transfer)

        if data.fee > 0:
            # Recorded as an expense so it reduces the source vault / total cash, but
            # WITHOUT _apply_expense_side_effects — no budget burn-down for a fee.
            fee_expense = Expense(
                category="Transfer fee",
                amount=data.fee,
                vault=data.from_vault,
                description=(
                    f"Fee: {data.from_vault.value} → {data.to_vault.value} transfer"
                ),
            )
            fee_expense = await self._expense_repo.create(fee_expense)
            transfer.fee_expense_id = fee_expense.id

        self._session.add(
            OutboxEvent(
                exchange="finguard.events",
                routing_key="finance.vault_transfer.recorded",
                payload={
                    "event_name": "finance.vault_transfer.recorded",
                    "emitted_at": datetime.now(UTC).isoformat(),
                    "payload": {
                        "transfer_id": str(transfer.id),
                        "from_vault": data.from_vault.value,
                        "to_vault": data.to_vault.value,
                        "amount": float(data.amount),
                        "fee": float(data.fee),
                        "recorded_by": str(current_user.id),
                    },
                },
            )
        )
        await self._session.commit()
        return transfer

    async def list_vault_transfers(
        self, limit: int = 100, offset: int = 0
    ) -> list[VaultTransfer]:
        return await self._vault_transfer_repo.list_all(limit=limit, offset=offset)

    async def get_vault_balances(self) -> VaultBalancesResponse:
        """Derive each vault's live balance from payments, expenses and transfers.

        ``balance = Σ payments_in + Σ transfers_in − Σ expenses − Σ transfers_out``;
        transfer fees are already inside the expense term (booked on the source
        vault), so they are not subtracted twice.  Every ``VaultType`` is listed.
        """
        payments_in = await self._payment_repo.totals_by_vault()
        expenses_out = await self._expense_repo.totals_by_vault()
        transfers_in = await self._vault_transfer_repo.in_totals_by_vault()
        transfers_out = await self._vault_transfer_repo.out_totals_by_vault()

        balances: list[VaultBalance] = []
        total = Decimal("0")
        for vault in VaultType:
            balance = (
                payments_in.get(vault, Decimal("0"))
                + transfers_in.get(vault, Decimal("0"))
                - expenses_out.get(vault, Decimal("0"))
                - transfers_out.get(vault, Decimal("0"))
            ).quantize(Decimal("0.01"))
            balances.append(VaultBalance(vault=vault, balance=balance))
            total += balance

        return VaultBalancesResponse(balances=balances, currency="KES", total=total)

    async def create_budget(self, data: BudgetCreate) -> Budget:
        budget = Budget(**data.model_dump())
        budget = await self._budget_repo.create(budget)
        await self._session.commit()
        return budget

    async def list_budgets(self) -> list[Budget]:
        return await self._budget_repo.list_all()

    # ── Cash Payments ─────────────────────────────────────────────────────────

    async def _enqueue_payment_receipt(self, invoice: Invoice, payment: Payment) -> None:
        """Queue a "payment received" receipt to the invoice's customer.

        Shared by the manual-cash and agent-reconciled payment paths. Enqueue-only
        (no commit) so it rides the caller's transaction — the receipt is atomic
        with the payment. A customer without an email is silently skipped inside
        ``enqueue_email`` (a receipt must never fail a payment). Call *after*
        re-projection so ``balance_due`` reflects this payment.
        """
        customer = await self._session.get(Customer, invoice.customer_id)
        await NotificationService(self._session).enqueue_email(
            to_email=customer.email if customer else None,
            to_name=customer.name if customer else None,
            subject=f"Payment received — invoice {invoice.invoice_number}",
            template="payment_receipt",
            context={
                "customer_name": customer.name if customer else None,
                "invoice_number": invoice.invoice_number,
                "amount": str(payment.amount),
                "currency": invoice.currency,
                "balance_due": str(invoice.balance_due),
                "vault": payment.vault.value,
            },
            idempotency_key=f"receipt:{payment.id}",
            category=EmailCategory.RECEIPT,
        )

    async def record_cash_payment(self, data: PaymentCreate, current_user: User) -> Payment:
        """
        Record a manual cash payment against an invoice.

        All mutations (invoice update + payment row + outbox event) are flushed
        together and committed in a single transaction — no partial writes are
        possible even if the process crashes after commit returns.

        The invoice row is locked FOR UPDATE before its balance is read so two
        concurrent payments against the same invoice serialise; without the lock
        both could read the same balance_due and over-credit the invoice.
        """
        invoice = await self._invoice_repo.get_by_id_for_update(data.invoice_id)
        if not invoice:
            raise NotFoundError("Invoice not found")

        if invoice.balance_due < data.amount:
            raise UnprocessableError(
                f"Payment amount {data.amount} exceeds balance due {invoice.balance_due}"
            )

        # Persist the payment record (the immutable money-movement row).
        payment = Payment(
            invoice_id=data.invoice_id,
            amount=data.amount,
            vault=VaultType.CASH,
            reference_note=data.reference_note,
            payment_date=data.payment_date,
            recorded_by=current_user.id,
        )
        payment = await self._payment_repo.create(payment)

        # Event sourcing: append payment_applied to the invoice log, then derive
        # the new amount_paid/balance_due/status by folding the full history.
        # The invoice's FOR UPDATE lock (acquired above) serialises concurrent
        # payments, so sequence allocation is race-free and the derived balance
        # can never be over-credited. The status flips to PARTIALLY_PAID or PAID
        # purely as a function of the events — the dashboard and Agent E watchdog
        # then read a consistent state.
        sequence = await self._invoice_event_repo.next_sequence(invoice.id)
        await self._invoice_event_repo.append(
            InvoiceEvent(
                invoice_id=invoice.id,
                sequence=sequence,
                event_type=InvoiceEventType.PAYMENT_APPLIED,
                amount=data.amount,
                payload={
                    "payment_id": str(payment.id),
                    "vault": VaultType.CASH.value,
                    "reference_note": data.reference_note,
                    "recorded_by": str(current_user.id),
                },
                occurred_at=data.payment_date,
                recorded_by=current_user.id,
            )
        )
        await self._project_invoice_from_events(invoice)

        # Emit event via transactional outbox — guaranteed delivery even on crash
        self._session.add(
            OutboxEvent(
                exchange="finguard.events",
                routing_key="payments.cash_recorded",
                payload={
                    "event_name": "payments.cash_recorded",
                    "emitted_at": datetime.now(UTC).isoformat(),
                    "payload": {
                        "payment_id": str(payment.id),
                        "invoice_id": str(data.invoice_id),
                        "amount": float(data.amount),
                        "vault": VaultType.CASH.value,
                        "recorded_by": str(current_user.id),
                        "balance_due_after": float(invoice.balance_due),
                    },
                },
            )
        )

        # Receipt to the customer, atomic with the payment (flushed on commit).
        await self._enqueue_payment_receipt(invoice, payment)

        await self._session.commit()
        return payment

    # ── Financial reports (CoreReports) ────────────────────────────────────────

    async def _fetch_report_aggregates(
        self, period_days: int
    ) -> tuple[list[tuple[str, Decimal, Decimal]], list[tuple[str, Decimal]], Decimal]:
        """Pull the trailing-window aggregates the report builders consume.

        Returns ``(monthly, expense_categories, output_vat)`` where ``monthly`` is
        oldest-first ``(YYYY-MM, revenue, opex)`` from ``ledger_entries``,
        ``expense_categories`` is debit totals by category (largest first), and
        ``output_vat`` is the VAT collected on invoices issued in the window.
        """
        monthly_rows = (
            await self._session.execute(
                text("""
                    SELECT
                        TO_CHAR(DATE_TRUNC('month', created_at), 'YYYY-MM') AS month,
                        COALESCE(SUM(CASE WHEN transaction_type = 'CREDIT'
                                         THEN amount ELSE 0 END), 0) AS revenue,
                        COALESCE(SUM(CASE WHEN transaction_type = 'DEBIT'
                                         THEN amount ELSE 0 END), 0) AS opex
                    FROM ledger_entries
                    WHERE created_at >= NOW() - make_interval(days => :days)
                    GROUP BY 1
                    ORDER BY 1
                """),
                {"days": period_days},
            )
        ).all()
        monthly = [
            (r[0], Decimal(r[1]), Decimal(r[2])) for r in monthly_rows
        ]

        category_rows = (
            await self._session.execute(
                text("""
                    SELECT COALESCE(category, 'Uncategorised') AS category,
                           COALESCE(SUM(amount), 0) AS amt
                    FROM ledger_entries
                    WHERE transaction_type = 'DEBIT'
                      AND created_at >= NOW() - make_interval(days => :days)
                    GROUP BY 1
                    ORDER BY amt DESC
                """),
                {"days": period_days},
            )
        ).all()
        expense_categories = [(r[0], Decimal(r[1])) for r in category_rows]

        output_vat = Decimal(
            (
                await self._session.execute(
                    text("""
                        SELECT COALESCE(SUM(tax), 0)
                        FROM invoices
                        WHERE created_at >= NOW() - make_interval(days => :days)
                    """),
                    {"days": period_days},
                )
            ).scalar_one()
        )
        return monthly, expense_categories, output_vat

    async def generate_report(
        self, report_type: ReportType, period_days: int = 365
    ) -> FinancialReport:
        """Generate one financial report from live ledger/invoice data."""
        monthly, expense_categories, output_vat = await self._fetch_report_aggregates(
            period_days
        )
        now = datetime.now(UTC)
        if report_type == ReportType.INCOME_STATEMENT:
            return build_income_statement(
                monthly=monthly,
                expense_categories=expense_categories,
                period_days=period_days,
                now=now,
            )
        if report_type == ReportType.CASH_FLOW:
            return build_cash_flow(monthly=monthly, period_days=period_days, now=now)
        return build_tax_liability(
            monthly=monthly,
            output_vat=output_vat,
            period_days=period_days,
            now=now,
        )

    async def get_report_catalog(self, period_days: int = 365) -> ReportCatalogResponse:
        """List the available reports with a live ready/no_data status."""
        monthly, _, output_vat = await self._fetch_report_aggregates(period_days)
        has_ledger = any(rev or opex for _, rev, opex in monthly)
        has_tax = output_vat > 0

        def status(ready: bool) -> str:
            return "ready" if ready else "no_data"

        reports = [
            ReportCatalogItem(
                report_type=ReportType.INCOME_STATEMENT,
                title="Income Statement",
                description="Revenue, operating expenses and net profit (P&L).",
                status=status(has_ledger),
            ),
            ReportCatalogItem(
                report_type=ReportType.CASH_FLOW,
                title="Cash Flow",
                description="Inflows, outflows and monthly burn over the period.",
                status=status(has_ledger),
            ),
            ReportCatalogItem(
                report_type=ReportType.TAX_LIABILITY,
                title="Tax Liability",
                description="Output VAT and an estimated corporate income-tax charge.",
                status=status(has_ledger or has_tax),
            ),
        ]
        return ReportCatalogResponse(reports=reports, currency="KES")
