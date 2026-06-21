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
    BankStatementLine,
    Budget,
    Expense,
    Invoice,
    InvoiceEvent,
    InvoiceEventType,
    InvoiceStatus,
    LedgerEntry,
    MpesaTransaction,
    OutboxEvent,
    Payment,
    VaultTransfer,
)
from src.domains.finance.repository import (
    BankStatementRepository,
    BudgetRepository,
    ExpenseRepository,
    InvoiceEventRepository,
    InvoiceRepository,
    LedgerRepository,
    MpesaRepository,
    PaymentRepository,
    VaultTransferRepository,
)
from src.domains.finance.schemas import (
    BankStatementLineImport,
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
    ReconciliationFlowResponse,
    SankeyLink,
    SankeyNode,
    VaultBalance,
    VaultBalancesResponse,
    VaultTransferCreate,
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
                nodes.append(SankeyNode(name=name, kind=kind))  # type: ignore[arg-type]
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
            label = rail_labels.get(vault)
            if label is None or amount <= 0:
                continue
            rail_by_status.setdefault(status, {})
            rail_by_status[status][label] = rail_by_status[status].get(label, Decimal("0")) + amount
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
                    SankeyLink(source=status_idx, target=node(rail_label, "rail"), value=money(amount))
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
                text("UPDATE mpesa_transactions SET is_reconciled = TRUE WHERE id = :id::uuid"),
                {"id": str(mpesa_uuid)},
            )
        if bank_uuid is not None:
            await self._session.execute(
                text("UPDATE bank_statement_lines SET is_reconciled = TRUE WHERE id = :id::uuid"),
                {"id": str(bank_uuid)},
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
        """
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
