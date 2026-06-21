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

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
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
from src.domains.intelligence.agents.c_reconciler import (
    run_bank_reconciliation,
    run_reconciliation,
)
from tests.conftest import TestingSessionLocal


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
