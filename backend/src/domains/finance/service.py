import uuid
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

import structlog
from pydantic import ValidationError
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import ConflictError, NotFoundError, UnprocessableError
from src.domains.finance.events import InvoiceState, fold_invoice_events
from src.domains.finance.models import (
    Budget,
    Expense,
    Invoice,
    InvoiceEvent,
    InvoiceEventType,
    LedgerEntry,
    MpesaTransaction,
    OutboxEvent,
    Payment,
)
from src.domains.finance.repository import (
    BudgetRepository,
    ExpenseRepository,
    InvoiceEventRepository,
    InvoiceRepository,
    LedgerRepository,
    MpesaRepository,
    PaymentRepository,
)
from src.domains.finance.schemas import (
    BudgetCreate,
    ExpenseCreate,
    InvoiceCreate,
    InvoiceUpdate,
    LedgerEntryCreate,
    MpesaCallbackPayload,
    MpesaStkCallback,
    MpesaTransactionResponse,
    PaymentCreate,
    ReceiptExpenseCreate,
)
from src.domains.finance.types import VaultType
from src.domains.identity.models import User

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

    async def _project_invoice_from_events(self, invoice: Invoice) -> InvoiceState:
        """Re-derive an invoice's monetary fields from its event log.

        Folds the full event history and applies the result to the materialized
        ``invoices`` row in-place (caller owns the commit).  ``amount_paid`` and
        ``balance_due`` are always overwritten so the row provably equals the
        fold; ``status``/``paid_at`` are only touched when a payment has been
        applied — manual statuses (DRAFT/SENT/OVERDUE) are left intact.
        """
        events = await self._invoice_event_repo.list_by_invoice(invoice.id)
        state = fold_invoice_events(events)
        invoice.amount_paid = state.amount_paid
        invoice.balance_due = state.balance_due
        if state.payment_status is not None:
            invoice.status = state.payment_status
            invoice.paid_at = state.paid_at
        return state

    async def update_invoice(self, invoice_id: uuid.UUID, data: InvoiceUpdate) -> Invoice:
        invoice = await self._invoice_repo.get_by_id(invoice_id)
        if not invoice:
            raise NotFoundError("Invoice not found")
        for field, value in data.model_dump(exclude_none=True).items():
            setattr(invoice, field, value)
        invoice = await self._invoice_repo.save(invoice)
        await self._session.commit()
        return invoice

    async def mark_invoice_paid(self, invoice_id: uuid.UUID) -> Invoice:
        invoice = await self._invoice_repo.get_by_id_for_update(invoice_id)
        if not invoice:
            raise NotFoundError("Invoice not found")
        # Settle by appending a payment_applied event for the outstanding balance,
        # then re-projecting — so the event log stays the single source of truth
        # and the row never drifts from ck_invoices_balance_due_consistent. A
        # no-op when the invoice is already fully settled.
        remaining = invoice.balance_due
        if remaining > Decimal("0"):
            now = datetime.now(UTC)
            sequence = await self._invoice_event_repo.next_sequence(invoice.id)
            await self._invoice_event_repo.append(
                InvoiceEvent(
                    invoice_id=invoice.id,
                    sequence=sequence,
                    event_type=InvoiceEventType.PAYMENT_APPLIED,
                    amount=remaining,
                    payload={"reason": "manual_settlement"},
                    occurred_at=now,
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

    async def create_budget(self, data: BudgetCreate) -> Budget:
        budget = Budget(**data.model_dump())
        budget = await self._budget_repo.create(budget)
        await self._session.commit()
        return budget

    async def list_budgets(self) -> list[Budget]:
        return await self._budget_repo.list_all()

    # ── Cash Payments ─────────────────────────────────────────────────────────

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

        await self._session.commit()
        return payment
