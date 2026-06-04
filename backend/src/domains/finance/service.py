import uuid
from datetime import UTC, datetime
from decimal import Decimal

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
    MpesaTransactionResponse,
    PaymentCreate,
)
from src.domains.finance.types import VaultType
from src.domains.identity.models import User
from src.infrastructure.message_bus.rabbitmq_publisher import publish


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
        from datetime import datetime

        invoice = await self._invoice_repo.get_by_id(invoice_id)
        if not invoice:
            raise NotFoundError("Invoice not found")
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

        await self._session.commit()
        await publish(
            "finguard.events",
            "expenses.created",
            {
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
        return expense

    async def list_expenses(self, limit: int = 100, offset: int = 0) -> list[Expense]:
        return await self._expense_repo.list_all(limit=limit, offset=offset)

    # ── M-Pesa ────────────────────────────────────────────────────────────────

    async def process_mpesa_callback(
        self, payload: MpesaCallbackPayload
    ) -> MpesaTransactionResponse | None:
        """
        Parse a Daraja STK Push callback, persist the transaction, and emit
        an `mpesa.reconciled` event for downstream agents.

        Returns None when the callback signals a failed payment (ResultCode != 0).
        """
        body = payload.Body
        stk = body.get("stkCallback", {})
        result_code: int = stk.get("ResultCode", -1)
        if result_code != 0:
            # Failed payment — nothing to persist
            return None

        # Extract fields from CallbackMetadata.Item list
        items: dict[str, str | int | float] = {
            item["Name"]: item.get("Value", "")
            for item in stk.get("CallbackMetadata", {}).get("Item", [])
        }
        trans_id = str(items.get("MpesaReceiptNumber", ""))
        amount = Decimal(str(items.get("Amount", 0)))
        phone = str(items.get("PhoneNumber", ""))
        bill_ref = stk.get("CheckoutRequestID", "")

        # Idempotent: skip if already recorded
        existing = await self._mpesa_repo.get_by_trans_id(trans_id)
        if existing:
            return MpesaTransactionResponse.model_validate(existing)

        txn = MpesaTransaction(
            trans_id=trans_id,
            amount=amount,
            phone=phone,
            bill_ref=bill_ref,
            vault=VaultType.MPESA,
        )
        txn = await self._mpesa_repo.create(txn)
        await self._session.commit()

        await publish(
            "finguard.events",
            "mpesa.reconciled",
            {
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
        """
        invoice = await self._invoice_repo.get_by_id(data.invoice_id)
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
