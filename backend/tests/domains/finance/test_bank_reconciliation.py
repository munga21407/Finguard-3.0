"""
Tests for bank-statement reconciliation and payment↔invoice linkage.

Covers:
  * importing bank statement lines (unreconciled);
  * run_bank_reconciliation matching a line to an open invoice → a
    Payment(vault=BANK) linked to the invoice, a payment_applied event, the bank
    line flipped to reconciled, and a drift-free event-log reconstruction;
  * M-Pesa reconciliation now also produces a Payment(vault=MPESA) linked to its
    invoice (previously it bumped invoice columns without a Payment row).

Data is crafted so Pass 1 (deterministic: amount ±1, date ±2 days, reference
substring) matches — Pass 2's Gemini scorer is never invoked, keeping the tests
offline and deterministic.
"""
from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from src.domains.finance.models import (
    BankStatementLine,
    Invoice,
    InvoiceStatus,
    MpesaTransaction,
    Payment,
)
from src.domains.finance.schemas import BankStatementLineImport, InvoiceCreate
from src.domains.finance.service import FinanceService
from src.domains.finance.types import VaultType
from src.domains.identity.models import User, UserRole
from src.domains.intelligence.agents.c_reconciler import (
    run_bank_reconciliation,
    run_reconciliation,
)
from tests.conftest import TestingSessionLocal


def _fake_user() -> User:
    return User(
        id=uuid.uuid4(),
        email=f"importer-{uuid.uuid4().hex[:8]}@finguard.local",
        hashed_password="x",
        full_name="Importer",
        role=UserRole.ACCOUNTANT,
        is_active=True,
        is_verified=True,
    )


async def _make_sent_invoice(customer_id: str, *, subtotal: str) -> tuple[uuid.UUID, str]:
    """Create a SENT invoice (the status the reconciler picks up) and return its id/number."""
    async with TestingSessionLocal() as session:
        svc = FinanceService(session)
        invoice = await svc.create_invoice(
            InvoiceCreate(
                customer_id=uuid.UUID(customer_id),
                invoice_number=f"INV-{uuid.uuid4().hex[:10].upper()}",
                subtotal=Decimal(subtotal),
                tax=Decimal("0"),
            )
        )
        invoice.status = InvoiceStatus.SENT
        await session.commit()
        return invoice.id, invoice.invoice_number


@pytest.mark.asyncio
async def test_import_bank_statement_lines_persists_unreconciled(
    seed_customer: str,
) -> None:
    async with TestingSessionLocal() as session:
        rows = await FinanceService(session).import_bank_statement_lines(
            [
                BankStatementLineImport(
                    amount=Decimal("2500"),
                    date=datetime.now(UTC),
                    reference_text="ACME deposit",
                    external_ref=f"TXN-{uuid.uuid4().hex[:10]}",
                )
            ]
        )
    assert len(rows) == 1
    line_id = rows[0].id

    async with TestingSessionLocal() as session:
        line = await session.get(BankStatementLine, line_id)
        assert line is not None
        assert line.amount == Decimal("2500")
        assert line.is_reconciled is False


@pytest.mark.asyncio
async def test_import_is_idempotent_on_external_ref(seed_customer: str) -> None:
    ref = f"TXN-{uuid.uuid4().hex[:10]}"
    line = BankStatementLineImport(
        amount=Decimal("3300"),
        date=datetime.now(UTC),
        reference_text="repeat upload",
        external_ref=ref,
    )

    async with TestingSessionLocal() as session:
        first = await FinanceService(session).import_bank_statement_lines([line])
    assert len(first) == 1

    # Re-uploading the same statement line (same external_ref) inserts nothing.
    async with TestingSessionLocal() as session:
        second = await FinanceService(session).import_bank_statement_lines([line])
    assert second == []

    # Duplicates within a single request are also collapsed.
    dup_ref = f"TXN-{uuid.uuid4().hex[:10]}"
    dup = BankStatementLineImport(
        amount=Decimal("100"), date=datetime.now(UTC), external_ref=dup_ref
    )
    async with TestingSessionLocal() as session:
        rows = await FinanceService(session).import_bank_statement_lines([dup, dup])
    assert len(rows) == 1

    async with TestingSessionLocal() as session:
        total = (
            await session.execute(
                select(BankStatementLine).where(BankStatementLine.external_ref == ref)
            )
        ).scalars().all()
    assert len(total) == 1


@pytest.mark.asyncio
async def test_import_stamps_importing_user(seed_customer: str) -> None:
    """Imported lines record who imported them (audit trail for the trust source)."""
    user = _fake_user()
    line = BankStatementLineImport(
        amount=Decimal("4100"),
        date=datetime.now(UTC),
        external_ref=f"TXN-{uuid.uuid4().hex[:10]}",
    )
    async with TestingSessionLocal() as session:
        rows = await FinanceService(session).import_bank_statement_lines([line], user)
        line_id = rows[0].id

    async with TestingSessionLocal() as session:
        stored = await session.get(BankStatementLine, line_id)
        assert stored is not None
        assert stored.imported_by == user.id


@pytest.mark.asyncio
async def test_bank_reconciliation_links_payment_to_invoice(
    seed_customer: str,
) -> None:
    invoice_id, invoice_number = await _make_sent_invoice(seed_customer, subtotal="1000")

    # A bank line whose amount equals the balance and whose reference contains the
    # invoice number → clean Pass 1 match.
    async with TestingSessionLocal() as session:
        line = BankStatementLine(
            amount=Decimal("1000"),
            date=datetime.now(UTC),
            reference_text=f"RTGS {invoice_number}",
            external_ref=f"TXN-{uuid.uuid4().hex[:10]}",
            is_reconciled=False,
        )
        session.add(line)
        await session.commit()
        line_id = line.id

    async with TestingSessionLocal() as session:
        report = await run_bank_reconciliation(session)
    assert report.matched_exact == 1

    async with TestingSessionLocal() as session:
        invoice = await session.get(Invoice, invoice_id)
        assert invoice is not None
        assert invoice.status == InvoiceStatus.PAID
        assert invoice.balance_due == Decimal("0")

        payments = (
            await session.execute(select(Payment).where(Payment.invoice_id == invoice_id))
        ).scalars().all()
        assert len(payments) == 1
        assert payments[0].vault == VaultType.BANK
        assert payments[0].bank_line_id == line_id
        assert payments[0].recorded_by is None

        line = await session.get(BankStatementLine, line_id)
        assert line is not None and line.is_reconciled is True

        # Event log stays complete: the fold equals the materialized row.
        _, state, _ = await FinanceService(session).reconstruct_invoice(invoice_id)
        assert state.amount_paid == invoice.amount_paid
        assert state.balance_due == invoice.balance_due


@pytest.mark.asyncio
async def test_mpesa_reconciliation_creates_linked_payment(
    seed_customer: str,
) -> None:
    invoice_id, invoice_number = await _make_sent_invoice(seed_customer, subtotal="750")

    async with TestingSessionLocal() as session:
        txn = MpesaTransaction(
            trans_id=f"R{uuid.uuid4().hex[:9].upper()}",
            amount=Decimal("750"),
            phone="254700000000",
            bill_ref=invoice_number,
            is_reconciled=False,
        )
        session.add(txn)
        await session.commit()
        txn_id = txn.id

    async with TestingSessionLocal() as session:
        report = await run_reconciliation(session)
    assert report.matched_exact == 1

    async with TestingSessionLocal() as session:
        payments = (
            await session.execute(select(Payment).where(Payment.invoice_id == invoice_id))
        ).scalars().all()
        assert len(payments) == 1
        assert payments[0].vault == VaultType.MPESA
        assert payments[0].mpesa_trans_id == txn_id

        txn = await session.get(MpesaTransaction, txn_id)
        assert txn is not None and txn.is_reconciled is True


def _import_payload() -> list[dict]:
    return [
        {
            "amount": 100,
            "date": datetime.now(UTC).isoformat(),
            "external_ref": f"TXN-{uuid.uuid4().hex[:10]}",
        }
    ]


@pytest.mark.asyncio
async def test_bank_import_requires_reconcile_permission(
    client: AsyncClient, auth_as: Callable[..., User]
) -> None:
    url = "/api/v1/finance/reconciliation/bank-statements/import"
    # Accountant holds finance:write but NOT finance:reconcile → forbidden.
    auth_as(UserRole.ACCOUNTANT)
    denied = await client.post(url, json=_import_payload())
    assert denied.status_code == 403

    # Manager holds finance:reconcile → allowed.
    auth_as(UserRole.MANAGER)
    allowed = await client.post(url, json=_import_payload())
    assert allowed.status_code == 201, allowed.text


@pytest.mark.asyncio
async def test_bank_import_requires_external_ref(client: AsyncClient) -> None:
    # Default OWNER auth; missing the required external_ref → validation error.
    res = await client.post(
        "/api/v1/finance/reconciliation/bank-statements/import",
        json=[{"amount": 100, "date": datetime.now(UTC).isoformat()}],
    )
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_concurrent_bank_reconciliation_does_not_double_pay(
    seed_customer: str,
) -> None:
    invoice_id, invoice_number = await _make_sent_invoice(seed_customer, subtotal="1000")
    async with TestingSessionLocal() as session:
        session.add(
            BankStatementLine(
                amount=Decimal("1000"),
                date=datetime.now(UTC),
                reference_text=f"RTGS {invoice_number}",
                external_ref=f"TXN-{uuid.uuid4().hex[:10]}",
                is_reconciled=False,
            )
        )
        await session.commit()

    async def _run() -> None:
        async with TestingSessionLocal() as session:
            await run_bank_reconciliation(session)

    # Two concurrent runs: FOR UPDATE SKIP LOCKED + the unique bank_line_id
    # constraint guarantee the line settles exactly once.
    await asyncio.gather(_run(), _run(), return_exceptions=True)

    async with TestingSessionLocal() as session:
        payments = (
            await session.execute(select(Payment).where(Payment.invoice_id == invoice_id))
        ).scalars().all()
        assert len(payments) == 1
        invoice = await session.get(Invoice, invoice_id)
        assert invoice is not None and invoice.balance_due == Decimal("0")
