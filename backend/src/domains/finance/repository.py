import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domains.finance.models import (
    Budget,
    Expense,
    Invoice,
    LedgerEntry,
    MpesaTransaction,
    Payment,
)


class LedgerRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, entry: LedgerEntry) -> LedgerEntry:
        self._session.add(entry)
        await self._session.flush()
        await self._session.refresh(entry)
        return entry

    async def list_by_account(self, account_id: uuid.UUID, limit: int = 50) -> list[LedgerEntry]:
        result = await self._session.execute(
            select(LedgerEntry)
            .where(LedgerEntry.account_id == account_id)
            .order_by(LedgerEntry.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())


class InvoiceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, invoice_id: uuid.UUID) -> Invoice | None:
        return await self._session.get(Invoice, invoice_id)

    async def get_by_number(self, number: str) -> Invoice | None:
        result = await self._session.execute(
            select(Invoice).where(Invoice.invoice_number == number)
        )
        return result.scalar_one_or_none()

    async def list_by_customer(self, customer_id: uuid.UUID) -> list[Invoice]:
        result = await self._session.execute(
            select(Invoice)
            .where(Invoice.customer_id == customer_id)
            .order_by(Invoice.created_at.desc())
        )
        return list(result.scalars().all())

    async def create(self, invoice: Invoice) -> Invoice:
        self._session.add(invoice)
        await self._session.flush()
        await self._session.refresh(invoice)
        return invoice

    async def save(self, invoice: Invoice) -> Invoice:
        await self._session.flush()
        await self._session.refresh(invoice)
        return invoice


class ExpenseRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, expense: Expense) -> Expense:
        self._session.add(expense)
        await self._session.flush()
        await self._session.refresh(expense)
        return expense

    async def list_all(self, limit: int = 100, offset: int = 0) -> list[Expense]:
        result = await self._session.execute(
            select(Expense).order_by(Expense.created_at.desc()).limit(limit).offset(offset)
        )
        return list(result.scalars().all())

    async def get_by_id(self, expense_id: uuid.UUID) -> Expense | None:
        return await self._session.get(Expense, expense_id)


class MpesaRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_trans_id(self, trans_id: str) -> MpesaTransaction | None:
        result = await self._session.execute(
            select(MpesaTransaction).where(MpesaTransaction.trans_id == trans_id)
        )
        return result.scalar_one_or_none()

    async def create(self, txn: MpesaTransaction) -> MpesaTransaction:
        self._session.add(txn)
        await self._session.flush()
        await self._session.refresh(txn)
        return txn

    async def save(self, txn: MpesaTransaction) -> MpesaTransaction:
        await self._session.flush()
        await self._session.refresh(txn)
        return txn


class BudgetRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, budget: Budget) -> Budget:
        self._session.add(budget)
        await self._session.flush()
        await self._session.refresh(budget)
        return budget

    async def list_all(self) -> list[Budget]:
        result = await self._session.execute(
            select(Budget).order_by(Budget.period_start.desc())
        )
        return list(result.scalars().all())


class PaymentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, payment: Payment) -> Payment:
        self._session.add(payment)
        await self._session.flush()
        await self._session.refresh(payment)
        return payment

    async def list_by_invoice(self, invoice_id: uuid.UUID) -> list[Payment]:
        result = await self._session.execute(
            select(Payment)
            .where(Payment.invoice_id == invoice_id)
            .order_by(Payment.payment_date.desc())
        )
        return list(result.scalars().all())
