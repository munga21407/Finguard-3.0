"""
Seed realistic demo data for a walkthrough: customers, products with stock
movements, invoices in a mix of lifecycle states, operating expenses, budgets,
and a couple of alerts (plus the low-stock alerts inventory raises on its own).

Everything is written through the real domain services (CRMService,
InventoryService, FinanceService, AlertService) so every invariant they
enforce — event-sourced invoice folding, weighted-average stock costing,
budget burn-down, low-stock alert transitions — holds exactly as it would in
production. Nothing here writes to the database directly.

Requires at least one existing user (log in / register once first, or run
``scripts.seed_users``) — that user is used as the "actor" recorded against
payments, stock movements, and audit-relevant actions.

Idempotent at the whole-run level: if the demo customer marker already exists,
the script skips entirely so re-running never duplicates data. Pass --force to
add another pass anyway (customers/products/invoices are individually
deduplicated by their unique keys; expenses, budgets, and alerts are not, so
--force will add duplicates of those).

Usage (from backend/):
    python -m scripts.seed_demo_data
    python -m scripts.seed_demo_data --force
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select

from src.core.exceptions import ConflictError
from src.domains.alerts.models import AlertSeverity, AlertType
from src.domains.alerts.schemas import AlertCreate
from src.domains.alerts.service import AlertService
from src.domains.crm.models import CustomerType
from src.domains.crm.repository import CustomerRepository
from src.domains.crm.schemas import CustomerCreate
from src.domains.crm.service import CRMService
from src.domains.finance.models import LedgerEntry, TransactionType
from src.domains.finance.repository import LedgerRepository
from src.domains.finance.schemas import (
    BudgetCreate,
    ExpenseCreate,
    InvoiceCreate,
    PaymentCreate,
    StockPurchaseCreate,
)
from src.domains.finance.service import FinanceService
from src.domains.finance.types import VaultType
from src.domains.identity.models import User
from src.domains.inventory.repository import ProductRepository
from src.domains.inventory.schemas import InventoryMovementCreate, ProductCreate
from src.domains.inventory.service import InventoryService
from src.domains.inventory.types import MovementReason, MovementType
from src.infrastructure.database.postgres import AsyncSessionLocal

logger = logging.getLogger("seed_demo_data")

# Presence of this customer marks the demo dataset as already seeded.
MARKER_CUSTOMER_EMAIL = "amina.njoroge@demo.finguard.co.ke"

# ledger_entries has no product/invoice/expense FK — it's a standalone general
# ledger feed (Agent D's cash-flow forecast and the finance reports read only
# from this table, not from invoices/payments/expenses directly), so the demo
# needs its own account id to post against.
DEMO_ACCOUNT_ID = uuid.uuid5(uuid.NAMESPACE_URL, "finguard.demo.main-account")

VAT_RATE = Decimal("0.16")  # Kenyan standard VAT

CUSTOMERS = [
    ("Amina Njoroge", "amina.njoroge@demo.finguard.co.ke", "+254712345001", CustomerType.INDIVIDUAL),
    ("Kevin Otieno", "kevin.otieno@demo.finguard.co.ke", "+254712345002", CustomerType.INDIVIDUAL),
    ("Wanjiru Kamau", "wanjiru.kamau@demo.finguard.co.ke", "+254712345003", CustomerType.INDIVIDUAL),
    ("Mercy Wambui", "mercy.wambui@demo.finguard.co.ke", "+254712345004", CustomerType.INDIVIDUAL),
    ("Sunrise Cafe Ltd", "accounts@sunrisecafe.demo.finguard.co.ke", "+254712345005", CustomerType.BUSINESS),
    ("Bright Star Academy", "finance@brightstar.demo.finguard.co.ke", "+254712345006", CustomerType.BUSINESS),
    ("Coastal Retailers Ltd", "procurement@coastalretail.demo.finguard.co.ke", "+254712345007", CustomerType.BUSINESS),
    ("Tembo Hardware Ltd", "billing@tembohardware.demo.finguard.co.ke", "+254712345008", CustomerType.BUSINESS),
]

# sku, name, category, cost_price, selling_price, reorder_level, reorder_qty,
# quantity received on the initial stock purchase, quantity sold since.
# Rice and Charcoal are deliberately oversold below their reorder level so
# inventory's own low-stock alert fires for real.
PRODUCTS = [
    ("GRC-SUGAR-2KG", "Sugar 2kg Packet", "Groceries", 210, 260, 40, 100, 150, 90),
    ("GRC-OIL-5L", "Cooking Oil 5L", "Groceries", 950, 1150, 15, 30, 40, 22),
    ("GRC-RICE-25KG", "Pishori Rice 25kg Bag", "Groceries", 3200, 3800, 8, 20, 12, 6),
    ("GRC-FLOUR-2KG", "Maize Flour 2kg", "Groceries", 130, 165, 60, 150, 200, 110),
    ("HH-SOAP-BAR", "Bar Soap 800g", "Household", 95, 130, 50, 100, 140, 80),
    ("DAIRY-MILK-500", "Fresh Milk 500ml", "Dairy", 45, 60, 100, 200, 260, 150),
    ("HH-DET-1KG", "Detergent Powder 1kg", "Household", 180, 230, 40, 80, 100, 55),
    ("BEV-TEA-500G", "Tea Leaves 500g", "Beverages", 240, 300, 30, 60, 70, 38),
    ("FUEL-CHARCOAL-5KG", "Charcoal 5kg Bag", "Household", 300, 400, 20, 40, 24, 8),
    ("BAKE-BREAD-400G", "White Bread 400g", "Bakery", 48, 65, 80, 150, 180, 95),
]

# category, budget amount for the current period. Category names must match
# the operating expenses below exactly — that's the key create_expense uses
# to burn down the matching budget's `spent`.
BUDGETS = [
    ("Rent", "Rent", Decimal("40000")),
    ("Utilities", "Utilities", Decimal("15000")),
    ("Marketing", "Marketing", Decimal("10000")),  # intentionally exceeded below
    ("Staff Salaries", "Salaries", Decimal("120000")),
]

# category, amount, vault, description — the marketing spend deliberately
# exceeds its 10,000 budget so the budget-overspend alert below is accurate.
OPERATING_EXPENSES = [
    ("Rent", Decimal("40000"), VaultType.BANK, "Shop rent — Westlands branch"),
    ("Utilities", Decimal("6200"), VaultType.MPESA, "KPLC electricity token"),
    ("Utilities", Decimal("3100"), VaultType.MPESA, "Nairobi Water bill"),
    ("Salaries", Decimal("85000"), VaultType.BANK, "Staff salaries — 3 employees"),
    ("Transport", Decimal("4500"), VaultType.CASH, "Fuel for delivery van"),
    ("Transport", Decimal("3800"), VaultType.CASH, "Matatu fare & courier"),
    ("Marketing", Decimal("15500"), VaultType.MPESA, "Social media ads + fliers"),
    ("Communication", Decimal("2500"), VaultType.MPESA, "Airtime & internet bundles"),
    ("Repairs & Maintenance", Decimal("7200"), VaultType.CASH, "Fridge repair"),
]

# customer index (into CUSTOMERS), subtotal, outcome.
InvoiceOutcome = str  # "paid" | "partial" | "sent_future" | "sent_overdue" | "cancelled" | "draft"
INVOICE_PLAN: list[tuple[int, Decimal, InvoiceOutcome]] = [
    (0, Decimal("15000"), "paid"),
    (1, Decimal("8200"), "paid"),
    (2, Decimal("42000"), "partial"),
    (3, Decimal("5400"), "paid"),
    (4, Decimal("120000"), "partial"),
    (5, Decimal("64000"), "sent_future"),
    (6, Decimal("235000"), "sent_overdue"),
    (7, Decimal("98000"), "sent_future"),
    (0, Decimal("11250"), "paid"),
    (4, Decimal("47500"), "cancelled"),
    (5, Decimal("18900"), "draft"),
    (6, Decimal("31200"), "sent_overdue"),
]


async def _get_actor(session) -> User:
    """The user recorded against payments / stock movements / alerts.

    Uses whichever account exists (the demo doesn't need a specific role) —
    log in once through the app, or run ``scripts.seed_users``, before seeding.
    """
    result = await session.execute(select(User).order_by(User.created_at).limit(1))
    user = result.scalar_one_or_none()
    if user is None:
        raise RuntimeError(
            "No user found — create an account (or run `python -m scripts.seed_users`) "
            "before seeding demo data."
        )
    return user


async def _seed_customers(crm: CRMService, repo: CustomerRepository) -> tuple[list, int]:
    ids = []
    created = 0
    for name, email, phone, ctype in CUSTOMERS:
        try:
            customer = await crm.create_customer(
                CustomerCreate(name=name, email=email, phone=phone, customer_type=ctype)
            )
            created += 1
            logger.info("Created customer: %s", name)
        except ConflictError:
            customer = await repo.get_by_email(email)
            logger.info("Customer already exists — reusing: %s", name)
        ids.append(customer.id)
    return ids, created


async def _seed_products(
    inventory: InventoryService,
    finance: FinanceService,
    product_repo: ProductRepository,
    actor: User,
) -> tuple[dict[str, object], int, int]:
    ids: dict[str, object] = {}
    products_created = 0
    purchases_created = 0
    for sku, name, category, cost, sell, reorder_level, reorder_qty, receive_qty, sale_qty in PRODUCTS:
        try:
            product = await inventory.create_product(
                ProductCreate(
                    sku=sku,
                    name=name,
                    category=category,
                    cost_price=Decimal(cost),
                    selling_price=Decimal(sell),
                    reorder_level=Decimal(reorder_level),
                    reorder_quantity=Decimal(reorder_qty),
                )
            )
            products_created += 1
            logger.info("Created product: %s (%s)", name, sku)

            await finance.create_stock_purchase(
                StockPurchaseCreate(
                    expense=ExpenseCreate(
                        category="Inventory Purchase",
                        amount=Decimal(cost) * Decimal(receive_qty),
                        vault=VaultType.BANK,
                    ),
                    product_id=product.id,
                    quantity=Decimal(receive_qty),
                    unit_cost=Decimal(cost),
                ),
                actor_id=actor.id,
            )
            purchases_created += 1

            await inventory.record_movement(
                product.id,
                InventoryMovementCreate(
                    movement_type=MovementType.SALE,
                    quantity=Decimal(sale_qty),
                    reason=MovementReason.SALE,
                    note="Demo point-of-sale activity",
                ),
                actor_id=actor.id,
            )
        except ConflictError:
            product = await product_repo.get_by_sku(sku)
            logger.info("Product already exists — skipping stock ops: %s", sku)
        ids[sku] = product.id
    return ids, products_created, purchases_created


async def _seed_budgets(finance: FinanceService) -> int:
    now = datetime.now(UTC)
    period_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    next_month = (period_start + timedelta(days=32)).replace(day=1)
    period_end = next_month - timedelta(seconds=1)

    existing_names = {b.name for b in await finance.list_budgets()}
    created = 0
    for name, category, amount in BUDGETS:
        if name in existing_names:
            logger.info("Budget already exists — skipping: %s", name)
            continue
        await finance.create_budget(
            BudgetCreate(
                name=name,
                category=category,
                amount=amount,
                period_start=period_start,
                period_end=period_end,
            )
        )
        created += 1
        logger.info("Created budget: %s (KES %s)", name, amount)
    return created


async def _seed_operating_expenses(finance: FinanceService) -> int:
    created = 0
    for category, amount, vault, description in OPERATING_EXPENSES:
        await finance.create_expense(
            ExpenseCreate(category=category, amount=amount, vault=vault)
        )
        created += 1
        logger.info("Recorded expense: %s — KES %s (%s)", description, amount, category)
    return created


async def _seed_invoices(
    finance: FinanceService, customer_ids: list, actor: User
) -> tuple[int, int]:
    now = datetime.now(UTC)
    invoices_created = 0
    payments_created = 0
    for i, (cust_idx, subtotal, outcome) in enumerate(INVOICE_PLAN, start=1):
        invoice_number = f"DEMO-{i:04d}"
        tax = (subtotal * VAT_RATE).quantize(Decimal("0.01"))
        if outcome == "sent_future":
            due_date = now + timedelta(days=21)
        elif outcome == "sent_overdue":
            due_date = now - timedelta(days=10)
        else:
            due_date = now + timedelta(days=14)

        try:
            invoice = await finance.create_invoice(
                InvoiceCreate(
                    customer_id=customer_ids[cust_idx],
                    invoice_number=invoice_number,
                    subtotal=subtotal,
                    tax=tax,
                    due_date=due_date,
                    notes="Demo invoice for walkthrough purposes.",
                )
            )
        except ConflictError:
            logger.info("Invoice already exists — skipping: %s", invoice_number)
            continue
        invoices_created += 1
        logger.info("Created invoice %s (%s, KES %s)", invoice_number, outcome, invoice.total)

        if outcome == "draft":
            continue

        await finance.send_invoice(invoice.id, actor)

        if outcome == "paid":
            await finance.record_cash_payment(
                PaymentCreate(invoice_id=invoice.id, amount=invoice.total, payment_date=now),
                actor,
            )
            payments_created += 1
        elif outcome == "partial":
            partial_amount = (invoice.total * Decimal("0.4")).quantize(Decimal("0.01"))
            await finance.record_cash_payment(
                PaymentCreate(invoice_id=invoice.id, amount=partial_amount, payment_date=now),
                actor,
            )
            payments_created += 1
        elif outcome == "cancelled":
            await finance.cancel_invoice(invoice.id, actor, reason="Customer cancelled order")
    return invoices_created, payments_created


_LEDGER_SPAN_DAYS = 75  # how far back the demo ledger history is spread


async def _seed_ledger_entries(session, customer_ids: list) -> int:
    """Mirror the payments/purchases/expenses above into ``ledger_entries``.

    This table is a standalone general ledger feed — nothing in the invoice/
    expense flow writes to it automatically — but it's what Agent D's cash-flow
    forecast and the finance reports actually read, so the demo needs entries
    here too or those views show a KES 0 balance despite the populated invoices.

    Spread across the last ``_LEDGER_SPAN_DAYS`` days (oldest first) rather than
    all dated "now": Agent D fits Holt-Winters on the daily series, so bunching
    every entry on one day gives it a single, huge net-outflow day to
    extrapolate — producing a wildly overstated 30-day burn projection. Real
    daily variance keeps the forecast sane.
    """
    repo = LedgerRepository(session)
    now = datetime.now(UTC)

    entries: list[tuple[uuid.UUID | None, TransactionType, Decimal, str, str]] = []

    for i, (cust_idx, subtotal, outcome) in enumerate(INVOICE_PLAN, start=1):
        if outcome not in ("paid", "partial"):
            continue
        total = subtotal + (subtotal * VAT_RATE).quantize(Decimal("0.01"))
        amount = total if outcome == "paid" else (total * Decimal("0.4")).quantize(Decimal("0.01"))
        entries.append(
            (
                customer_ids[cust_idx],
                TransactionType.CREDIT,
                amount,
                f"Payment received — DEMO-{i:04d}",
                f"DEMO-{i:04d}",
            )
        )

    for sku, name, _category, cost, _sell, _reorder_level, _reorder_qty, receive_qty, _sale_qty in PRODUCTS:
        entries.append(
            (
                None,
                TransactionType.DEBIT,
                Decimal(cost) * Decimal(receive_qty),
                f"Stock purchase — {name}",
                sku,
            )
        )

    for category, amount, _vault, description in OPERATING_EXPENSES:
        entries.append((None, TransactionType.DEBIT, amount, description, category))

    created = 0
    denom = max(len(entries) - 1, 1)
    for idx, (customer_id, ttype, amount, description, reference) in enumerate(entries):
        days_ago = _LEDGER_SPAN_DAYS - (idx * _LEDGER_SPAN_DAYS // denom)
        occurred_at = now - timedelta(days=days_ago, hours=(idx * 7) % 24)
        await repo.create(
            LedgerEntry(
                account_id=DEMO_ACCOUNT_ID,
                customer_id=customer_id,
                transaction_type=ttype,
                amount=amount,
                description=description,
                reference=reference,
                created_at=occurred_at,
            )
        )
        created += 1

    await session.commit()
    logger.info("Posted %d ledger entries against demo account %s", created, DEMO_ACCOUNT_ID)
    return created


async def _seed_alerts(alerts: AlertService) -> int:
    await alerts.create_alert(
        AlertCreate(
            type=AlertType.ANOMALY,
            severity=AlertSeverity.WARNING,
            title="Unusual spike in Transport expenses",
            body=(
                "Transport & fuel spend this week is well above the trailing "
                "average — worth a quick check against delivery logs."
            ),
            source_agent="agent_e_watchdog",
        )
    )
    await alerts.create_alert(
        AlertCreate(
            type=AlertType.BUDGET_OVERSPEND,
            severity=AlertSeverity.CRITICAL,
            title="Marketing budget exceeded",
            body="Marketing spend (KES 15,500) has exceeded the period budget of KES 10,000.",
            source_agent="agent_e_watchdog",
        )
    )
    return 2


async def seed(*, force: bool) -> dict[str, int]:
    async with AsyncSessionLocal() as session:
        customer_repo = CustomerRepository(session)
        product_repo = ProductRepository(session)
        crm = CRMService(session)
        inventory = InventoryService(session)
        finance = FinanceService(session)
        alerts = AlertService(session)

        marker = await customer_repo.get_by_email(MARKER_CUSTOMER_EMAIL)
        if marker is not None and not force:
            logger.warning(
                "Demo data already seeded (found %s) — pass --force to add another pass.",
                MARKER_CUSTOMER_EMAIL,
            )
            return {"skipped": 1}

        actor = await _get_actor(session)
        logger.info("Seeding demo data as actor: %s", actor.email)

        customer_ids, customers_created = await _seed_customers(crm, customer_repo)
        _product_ids, products_created, purchases_created = await _seed_products(
            inventory, finance, product_repo, actor
        )
        budgets_created = await _seed_budgets(finance)
        expenses_created = await _seed_operating_expenses(finance)
        invoices_created, payments_created = await _seed_invoices(finance, customer_ids, actor)
        ledger_entries_created = await _seed_ledger_entries(session, customer_ids)
        alerts_created = await _seed_alerts(alerts)

        return {
            "customers": customers_created,
            "products": products_created,
            "stock_purchases": purchases_created,
            "budgets": budgets_created,
            "expenses": expenses_created + purchases_created,
            "invoices": invoices_created,
            "payments": payments_created,
            "ledger_entries": ledger_entries_created,
            "alerts": alerts_created,
        }


async def _amain(force: bool) -> None:
    result = await seed(force=force)
    if result.get("skipped"):
        return
    logger.info("Demo data seed complete: %s", result)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force",
        action="store_true",
        help="Seed again even if demo data already exists (customers/products/"
        "invoices stay deduplicated; expenses/budgets/alerts will duplicate).",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    asyncio.run(_amain(args.force))


if __name__ == "__main__":
    main()
