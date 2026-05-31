import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.database.postgres import get_db
from src.domains.finance.schemas import (
    BudgetCreate,
    BudgetResponse,
    InvoiceCreate,
    InvoiceResponse,
    InvoiceUpdate,
    LedgerEntryCreate,
    LedgerEntryResponse,
)
from src.domains.finance.service import FinanceService

router = APIRouter()

DBSession = Annotated[AsyncSession, Depends(get_db)]


@router.post("/ledger", response_model=LedgerEntryResponse, status_code=201)
async def post_ledger_entry(data: LedgerEntryCreate, db: DBSession) -> LedgerEntryResponse:
    entry = await FinanceService(db).post_ledger_entry(data)
    return LedgerEntryResponse.model_validate(entry)


@router.post("/invoices", response_model=InvoiceResponse, status_code=201)
async def create_invoice(data: InvoiceCreate, db: DBSession) -> InvoiceResponse:
    invoice = await FinanceService(db).create_invoice(data)
    return InvoiceResponse.model_validate(invoice)


@router.patch("/invoices/{invoice_id}", response_model=InvoiceResponse)
async def update_invoice(invoice_id: uuid.UUID, data: InvoiceUpdate, db: DBSession) -> InvoiceResponse:
    invoice = await FinanceService(db).update_invoice(invoice_id, data)
    return InvoiceResponse.model_validate(invoice)


@router.post("/invoices/{invoice_id}/pay", response_model=InvoiceResponse)
async def mark_invoice_paid(invoice_id: uuid.UUID, db: DBSession) -> InvoiceResponse:
    invoice = await FinanceService(db).mark_invoice_paid(invoice_id)
    return InvoiceResponse.model_validate(invoice)


@router.post("/budgets", response_model=BudgetResponse, status_code=201)
async def create_budget(data: BudgetCreate, db: DBSession) -> BudgetResponse:
    budget = await FinanceService(db).create_budget(data)
    return BudgetResponse.model_validate(budget)


@router.get("/budgets", response_model=list[BudgetResponse])
async def list_budgets(db: DBSession) -> list[BudgetResponse]:
    budgets = await FinanceService(db).list_budgets()
    return [BudgetResponse.model_validate(b) for b in budgets]
