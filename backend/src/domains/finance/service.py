import uuid
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

import structlog
from pydantic import ValidationError
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import ConflictError, NotFoundError, UnprocessableError
from src.domains.finance.models import (
    Budget,
    Expense,
    Invoice,
    InvoiceStatus,
    LedgerEntry,
    MpesaTransaction,
    OutboxEvent,
    Payment,
)
from src.domains.finance.repository import (
    BudgetRepository,
    ExpenseRepository,
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
        self._session.add(
            OutboxEvent(
                exchange="finguard.finance",
                routing_key="finance.invoice.created",
                payload={"invoice_id": str(invoice.id), "customer_id": str(invoice.customer_id)},
            )
        )
        await self._session.commit()
        return invoice

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
        # Settle the monetary fields too — not just status/paid_at.  Leaving
        # amount_paid/balance_due untouched would violate the
        # ck_invoices_balance_due_consistent constraint (balance_due =
        # total - amount_paid) and leave a "paid" invoice with a non-zero balance.
        invoice.amount_paid = invoice.total
        invoice.balance_due = Decimal("0")
        invoice.status = InvoiceStatus.PAID
        invoice.paid_at = datetime.now(UTC)
        invoice = await self._invoice_repo.save(invoice)
        await self._session.commit()
        return invoice

    # ── Expenses ──────────────────────────────────────────────────────────────

    async def create_expense(self, data: ExpenseCreate) -> Expense:
        expense = Expense(**data.model_dump())
        expense = await self._expense_repo.create(expense)

        # Increment the spent counter on every budget whose category and active
        # period match this expense.  Executed inside the same transaction as the
        # expense INSERT so Agent E's watchdog always reads a consistent burn rate.
        # If no budget row matches the UPDATE is a safe no-op (0 rows affected).
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

        # Emit via the transactional outbox — written in the SAME transaction as
        # the expense INSERT and budget UPDATE.  Previously this published to
        # RabbitMQ *after* commit, so a broker outage silently dropped the event
        # while the database row persisted.  The projector now delivers it with
        # at-least-once semantics.
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
                        "source": "database.expenses",
                    },
                },
            )
        )
        await self._session.commit()
        return expense

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

        # Update invoice running totals
        invoice.amount_paid += data.amount
        invoice.balance_due -= data.amount
        if invoice.balance_due == Decimal("0"):
            invoice.status = InvoiceStatus.PAID
            invoice.paid_at = datetime.now(UTC)
        else:
            # Partial settlement — reflect it in the status so the dashboard and
            # Agent E watchdog don't treat a part-paid invoice as still fully open.
            invoice.status = InvoiceStatus.PARTIALLY_PAID

        # Persist the payment record
        payment = Payment(
            invoice_id=data.invoice_id,
            amount=data.amount,
            vault=VaultType.CASH,
            reference_note=data.reference_note,
            payment_date=data.payment_date,
            recorded_by=current_user.id,
        )
        payment = await self._payment_repo.create(payment)

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
