// ─── Finance API ──────────────────────────────────────────────────────────────
// Typed wrappers over the finance + CRM endpoints used by the invoice flow.
// Types come from the generated OpenAPI schema (src/types/api.ts) so they stay
// in sync with the backend Pydantic models.

import httpClient from "@/lib/api/http-client";
import { ENDPOINTS } from "@/lib/api/endpoints";
import type {
  ApiBankStatementImport,
  ApiBankStatementLine,
  ApiBudget,
  ApiCustomer,
  ApiCustomerCreate,
  ApiExpense,
  ApiInvoice,
  ApiInvoiceCreate,
  ApiPayable,
  ApiPayableCreate,
  ApiPayableQueue,
  ApiReceiptExpenseCreate,
  ApiReconciliationFlow,
  ApiVaultBalances,
  ApiVaultTransfer,
  ApiVaultTransferCreate,
} from "@/types/api";

export async function listCustomers(): Promise<ApiCustomer[]> {
  const { data } = await httpClient.get<ApiCustomer[]>(ENDPOINTS.CRM.CUSTOMERS);
  return data;
}

export async function listInvoices(): Promise<ApiInvoice[]> {
  const { data } = await httpClient.get<ApiInvoice[]>(ENDPOINTS.FINANCE.INVOICES);
  return data;
}

export async function listExpenses(): Promise<ApiExpense[]> {
  const { data } = await httpClient.get<ApiExpense[]>(ENDPOINTS.FINANCE.EXPENSES);
  return data;
}

export async function listBudgets(): Promise<ApiBudget[]> {
  const { data } = await httpClient.get<ApiBudget[]>(ENDPOINTS.FINANCE.BUDGETS);
  return data;
}

/**
 * Invoice-lifecycle → settlement-rail Sankey flow (Total Billed → status →
 * reconciled M-Pesa / Bank rails), computed server-side from invoice_events and
 * Agent C reconciliation. Powers the Overview reconciliation diagram.
 */
export async function getReconciliationFlow(): Promise<ApiReconciliationFlow> {
  const { data } = await httpClient.get<ApiReconciliationFlow>(
    ENDPOINTS.FINANCE.RECONCILIATION_FLOW
  );
  return data;
}

/**
 * Import bank statement lines for Agent C to reconcile against open invoices.
 * Lines land unreconciled; the batch job later matches them and records a
 * Payment(vault=BANK), which then surfaces on the Overview reconciliation Sankey.
 */
export async function importBankStatements(
  lines: ApiBankStatementImport[]
): Promise<ApiBankStatementLine[]> {
  const { data } = await httpClient.post<ApiBankStatementLine[]>(
    ENDPOINTS.FINANCE.BANK_STATEMENTS_IMPORT,
    lines
  );
  return data;
}

/** List imported bank statement lines, optionally filtered by review status. */
export async function listBankStatements(
  reviewStatus?: string
): Promise<ApiBankStatementLine[]> {
  const { data } = await httpClient.get<ApiBankStatementLine[]>(
    ENDPOINTS.FINANCE.BANK_STATEMENTS,
    { params: reviewStatus ? { review_status: reviewStatus } : undefined }
  );
  return data;
}

/** Approve a pending bank line (maker-checker; approver must differ from importer). */
export async function approveBankStatement(id: string): Promise<ApiBankStatementLine> {
  const { data } = await httpClient.post<ApiBankStatementLine>(
    ENDPOINTS.FINANCE.BANK_STATEMENT_APPROVE(id)
  );
  return data;
}

/** Reject a pending bank line so it is never reconciled. */
export async function rejectBankStatement(id: string): Promise<ApiBankStatementLine> {
  const { data } = await httpClient.post<ApiBankStatementLine>(
    ENDPOINTS.FINANCE.BANK_STATEMENT_REJECT(id)
  );
  return data;
}

/** Live balance of each vault (M-Pesa / Cash / Bank) + the total cash position. */
export async function getVaultBalances(): Promise<ApiVaultBalances> {
  const { data } = await httpClient.get<ApiVaultBalances>(
    ENDPOINTS.FINANCE.VAULT_BALANCES
  );
  return data;
}

export async function listVaultTransfers(): Promise<ApiVaultTransfer[]> {
  const { data } = await httpClient.get<ApiVaultTransfer[]>(
    ENDPOINTS.FINANCE.VAULT_TRANSFERS
  );
  return data;
}

/** Move the business's own money between vaults (optional fee booked as an expense). */
export async function createVaultTransfer(
  body: ApiVaultTransferCreate
): Promise<ApiVaultTransfer> {
  const { data } = await httpClient.post<ApiVaultTransfer>(
    ENDPOINTS.FINANCE.VAULT_TRANSFERS,
    body
  );
  return data;
}

export async function createCustomer(
  body: ApiCustomerCreate
): Promise<ApiCustomer> {
  const { data } = await httpClient.post<ApiCustomer>(
    ENDPOINTS.CRM.CUSTOMERS,
    body
  );
  return data;
}

export async function createInvoice(
  body: ApiInvoiceCreate
): Promise<ApiInvoice> {
  const { data } = await httpClient.post<ApiInvoice>(
    ENDPOINTS.FINANCE.INVOICES,
    body
  );
  return data;
}

/**
 * Persist a reviewed receipt scan as an expense.  The OCR + categorisation
 * happens in the intelligence domain (scanReceipt); this writes the
 * user-verified fields via POST /finance/receipts.
 */
export async function createReceiptExpense(
  body: ApiReceiptExpenseCreate
): Promise<ApiExpense> {
  const { data } = await httpClient.post<ApiExpense>(
    ENDPOINTS.FINANCE.RECEIPTS,
    body
  );
  return data;
}

// ─── Accounts payable (approval queue) ──────────────────────────────────────

/** In-flight payables (pending/approved/scheduled) plus summary KPIs. */
export async function getPayableQueue(): Promise<ApiPayableQueue> {
  const { data } = await httpClient.get<ApiPayableQueue>(
    ENDPOINTS.FINANCE.PAYABLES_QUEUE
  );
  return data;
}

/** Submit a bill into the AP queue (lands at PENDING_REVIEW, no budget burn). */
export async function createPayable(body: ApiPayableCreate): Promise<ApiPayable> {
  const { data } = await httpClient.post<ApiPayable>(ENDPOINTS.FINANCE.PAYABLES, body);
  return data;
}

/** Approve a pending payable (reviewer must differ from submitter). */
export async function approvePayable(id: string): Promise<ApiPayable> {
  const { data } = await httpClient.post<ApiPayable>(
    ENDPOINTS.FINANCE.PAYABLE_APPROVE(id)
  );
  return data;
}

/** Reject a pending payable. */
export async function rejectPayable(id: string): Promise<ApiPayable> {
  const { data } = await httpClient.post<ApiPayable>(
    ENDPOINTS.FINANCE.PAYABLE_REJECT(id)
  );
  return data;
}

/** Schedule an approved payable for payment. */
export async function schedulePayable(id: string): Promise<ApiPayable> {
  const { data } = await httpClient.post<ApiPayable>(
    ENDPOINTS.FINANCE.PAYABLE_SCHEDULE(id)
  );
  return data;
}
