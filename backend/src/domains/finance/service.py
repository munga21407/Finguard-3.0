import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import ConflictException, NotFoundException
from src.domains.finance.models import (
    Budget,
    Expense,
    Invoice,
    InvoiceStatus,
    LedgerEntry,
    MpesaTransaction,
    OutboxEvent,
)
from src.domains.finance.types import VaultType
from src.domains.finance.repository import (
    BudgetRepository,
    ExpenseRepository,
    InvoiceRepository,
    LedgerRepository,
    MpesaRepository,
)
from src.domains.finance.schemas import (
    BudgetCreate,
    ExpenseCreate,
    InvoiceCreate,
    InvoiceUpdate,
    LedgerEntryCreate,
    MpesaCallbackPayload,
    MpesaTransactionResponse,
)
from src.infrastructure.message_bus.rabbitmq_publisher import publish


class FinanceService:
    def __init__(self, session: AsyncSession) -> None:
        self._ledger_repo = LedgerRepository(session)
        self._invoice_repo = InvoiceRepository(session)
        self._budget_repo = BudgetRepository(session)
        self._expense_repo = ExpenseRepository(session)
        self._mpesa_repo = MpesaRepository(session)
        self._session = session

    async def post_ledger_entry(self, data: LedgerEntryCreate) -> LedgerEntry:
        entry = LedgerEntry(**data.model_dump())
        entry = await self._ledger_repo.create(entry)
        await self._session.commit()
        return entry

    async def create_invoice(self, data: InvoiceCreate) -> Invoice:
        if await self._invoice_repo.get_by_number(data.invoice_number):
            raise ConflictException(f"Invoice {data.invoice_number} already exists")
        total = data.subtotal + data.tax
        invoice = Invoice(**data.model_dump(), total=total)
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
            raise NotFoundException("Invoice not found")
        for field, value in data.model_dump(exclude_none=True).items():
            setattr(invoice, field, value)
        invoice = await self._invoice_repo.save(invoice)
        await self._session.commit()
        return invoice

    async def mark_invoice_paid(self, invoice_id: uuid.UUID) -> Invoice:
        from datetime import datetime, timezone

        invoice = await self._invoice_repo.get_by_id(invoice_id)
        if not invoice:
            raise NotFoundException("Invoice not found")
        invoice.status = InvoiceStatus.PAID
        invoice.paid_at = datetime.now(timezone.utc)
        invoice = await self._invoice_repo.save(invoice)
        await self._session.commit()
        return invoice

    # ── Expenses ──────────────────────────────────────────────────────────────

    async def create_expense(self, data: ExpenseCreate) -> Expense:
        expense = Expense(**data.model_dump())
        expense = await self._expense_repo.create(expense)
        await self._session.commit()
        await publish(
            "finguard.events",
            "expenses.created",
            {
                "event_name": "expenses.created",
                "emitted_at": datetime.now(timezone.utc).isoformat(),
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

    async def process_mpesa_callback(self, payload: MpesaCallbackPayload) -> MpesaTransactionResponse | None:
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
                "emitted_at": datetime.now(timezone.utc).isoformat(),
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
            raise NotFoundException("Invoice not found")
        return invoice

    async def create_budget(self, data: BudgetCreate) -> Budget:
        budget = Budget(**data.model_dump())
        budget = await self._budget_repo.create(budget)
        await self._session.commit()
        return budget

    async def list_budgets(self) -> list[Budget]:
        return await self._budget_repo.list_all()
