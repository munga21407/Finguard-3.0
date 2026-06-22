import uuid
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domains.finance.models import (
    BankStatementLine,
    Budget,
    Expense,
    Invoice,
    InvoiceEvent,
    InvoiceStatus,
    LedgerEntry,
    MpesaTransaction,
    Payment,
    VaultTransfer,
)
from src.domains.finance.types import VaultType


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

    async def get_by_id_for_update(self, invoice_id: uuid.UUID) -> Invoice | None:
        """
        Fetch an invoice with a row-level write lock (SELECT … FOR UPDATE).

        Used by payment application so concurrent payments against the same
        invoice serialise — preventing a lost-update race where two requests
        both read the same balance_due and over-credit the invoice.
        """
        return await self._session.get(Invoice, invoice_id, with_for_update=True)

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

    async def status_aggregates(self) -> list[tuple[InvoiceStatus, Decimal, Decimal]]:
        """``(status, Σ total, Σ amount_paid)`` over non-cancelled invoices.

        Feeds the reconciliation-flow Sankey: the materialized ``invoices`` row is
        the synchronous projection of the ``invoice_events`` fold, so grouping it
        by status yields the lifecycle distribution without replaying every event.
        """
        result = await self._session.execute(
            select(
                Invoice.status,
                func.coalesce(func.sum(Invoice.total), 0),
                func.coalesce(func.sum(Invoice.amount_paid), 0),
            )
            .where(Invoice.status != InvoiceStatus.CANCELLED)
            .group_by(Invoice.status)
        )
        return [(row[0], Decimal(row[1]), Decimal(row[2])) for row in result.all()]


class InvoiceEventRepository:
    """Append-only access to the invoice event log.

    There is no update or delete — events are immutable.  ``append`` must be
    called while the parent invoice row is held ``FOR UPDATE`` so concurrent
    writers cannot allocate the same ``sequence``.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def next_sequence(self, invoice_id: uuid.UUID) -> int:
        """Next monotonic sequence for an invoice (1 for the first event)."""
        current = await self._session.scalar(
            select(func.max(InvoiceEvent.sequence)).where(
                InvoiceEvent.invoice_id == invoice_id
            )
        )
        return (current or 0) + 1

    async def append(self, event: InvoiceEvent) -> InvoiceEvent:
        self._session.add(event)
        await self._session.flush()
        await self._session.refresh(event)
        return event

    async def list_by_invoice(self, invoice_id: uuid.UUID) -> list[InvoiceEvent]:
        result = await self._session.execute(
            select(InvoiceEvent)
            .where(InvoiceEvent.invoice_id == invoice_id)
            .order_by(InvoiceEvent.sequence.asc())
        )
        return list(result.scalars().all())


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

    async def totals_by_vault(self) -> dict[VaultType, Decimal]:
        """Σ expense amount per vault — the outflow side of each vault balance.

        Includes transfer fees (booked as expenses on the source vault).
        """
        result = await self._session.execute(
            select(Expense.vault, func.coalesce(func.sum(Expense.amount), 0)).group_by(
                Expense.vault
            )
        )
        return {row[0]: Decimal(row[1]) for row in result.all()}


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


class BankStatementRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def bulk_create(self, lines: list[BankStatementLine]) -> list[BankStatementLine]:
        """Insert imported bank statement lines (left unreconciled for Agent C)."""
        self._session.add_all(lines)
        await self._session.flush()
        for line in lines:
            await self._session.refresh(line)
        return lines

    async def get_by_id(self, line_id: uuid.UUID) -> BankStatementLine | None:
        return await self._session.get(BankStatementLine, line_id)

    async def list_all(
        self, *, review_status: str | None = None, limit: int = 100, offset: int = 0
    ) -> list[BankStatementLine]:
        stmt = select(BankStatementLine)
        if review_status is not None:
            stmt = stmt.where(BankStatementLine.review_status == review_status)
        stmt = stmt.order_by(BankStatementLine.date.desc()).limit(limit).offset(offset)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def existing_external_refs(self, refs: list[str]) -> set[str]:
        """Subset of ``refs`` already present — the import idempotency check."""
        if not refs:
            return set()
        result = await self._session.execute(
            select(BankStatementLine.external_ref).where(
                BankStatementLine.external_ref.in_(refs)
            )
        )
        return {row[0] for row in result.all() if row[0] is not None}


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

    async def rail_aggregates(self) -> list[tuple[InvoiceStatus, VaultType, Decimal]]:
        """``(invoice.status, payment.vault, Σ amount)`` over non-cancelled invoices.

        The exact, per-invoice settlement-rail split feeding the reconciliation
        Sankey's Stage 2 → Stage 3: every Payment is joined to its invoice and
        grouped by the invoice's current status and the payment's rail.
        """
        result = await self._session.execute(
            select(Invoice.status, Payment.vault, func.coalesce(func.sum(Payment.amount), 0))
            .join(Invoice, Invoice.id == Payment.invoice_id)
            .where(Invoice.status != InvoiceStatus.CANCELLED)
            .group_by(Invoice.status, Payment.vault)
        )
        return [(row[0], row[1], Decimal(row[2])) for row in result.all()]

    async def totals_by_vault(self) -> dict[VaultType, Decimal]:
        """Σ payment amount per vault — the inflow side of each vault balance."""
        result = await self._session.execute(
            select(Payment.vault, func.coalesce(func.sum(Payment.amount), 0)).group_by(
                Payment.vault
            )
        )
        return {row[0]: Decimal(row[1]) for row in result.all()}


class VaultTransferRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, transfer: VaultTransfer) -> VaultTransfer:
        self._session.add(transfer)
        await self._session.flush()
        await self._session.refresh(transfer)
        return transfer

    async def list_all(self, limit: int = 100, offset: int = 0) -> list[VaultTransfer]:
        result = await self._session.execute(
            select(VaultTransfer)
            .order_by(VaultTransfer.occurred_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def in_totals_by_vault(self) -> dict[VaultType, Decimal]:
        """Σ transfer amount received per ``to_vault``."""
        result = await self._session.execute(
            select(
                VaultTransfer.to_vault, func.coalesce(func.sum(VaultTransfer.amount), 0)
            ).group_by(VaultTransfer.to_vault)
        )
        return {row[0]: Decimal(row[1]) for row in result.all()}

    async def out_totals_by_vault(self) -> dict[VaultType, Decimal]:
        """Σ transfer amount sent per ``from_vault`` (the fee is a separate expense)."""
        result = await self._session.execute(
            select(
                VaultTransfer.from_vault, func.coalesce(func.sum(VaultTransfer.amount), 0)
            ).group_by(VaultTransfer.from_vault)
        )
        return {row[0]: Decimal(row[1]) for row in result.all()}
