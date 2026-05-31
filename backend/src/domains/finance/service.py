import uuid
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import ConflictException, NotFoundException
from src.domains.finance.models import Budget, Invoice, InvoiceStatus, LedgerEntry, OutboxEvent
from src.domains.finance.repository import BudgetRepository, InvoiceRepository, LedgerRepository
from src.domains.finance.schemas import BudgetCreate, InvoiceCreate, InvoiceUpdate, LedgerEntryCreate


class FinanceService:
    def __init__(self, session: AsyncSession) -> None:
        self._ledger_repo = LedgerRepository(session)
        self._invoice_repo = InvoiceRepository(session)
        self._budget_repo = BudgetRepository(session)
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

    async def create_budget(self, data: BudgetCreate) -> Budget:
        budget = Budget(**data.model_dump())
        budget = await self._budget_repo.create(budget)
        await self._session.commit()
        return budget

    async def list_budgets(self) -> list[Budget]:
        return await self._budget_repo.list_all()
