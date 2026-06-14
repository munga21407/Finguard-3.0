// ─── Finance API ──────────────────────────────────────────────────────────────
// Typed wrappers over the finance + CRM endpoints used by the invoice flow.
// Types come from the generated OpenAPI schema (src/types/api.ts) so they stay
// in sync with the backend Pydantic models.

import httpClient from "@/lib/api/http-client";
import { ENDPOINTS } from "@/lib/api/endpoints";
import type {
  ApiBudget,
  ApiCustomer,
  ApiCustomerCreate,
  ApiExpense,
  ApiInvoice,
  ApiInvoiceCreate,
  ApiReceiptExpenseCreate,
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
