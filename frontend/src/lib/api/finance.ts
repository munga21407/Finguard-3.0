// ─── Finance API ──────────────────────────────────────────────────────────────
// Typed wrappers over the finance + CRM endpoints used by the invoice flow.
// Types come from the generated OpenAPI schema (src/types/api.ts) so they stay
// in sync with the backend Pydantic models.

import httpClient from "@/lib/api/http-client";
import { ENDPOINTS } from "@/lib/api/endpoints";
import type {
  ApiCustomer,
  ApiCustomerCreate,
  ApiInvoice,
  ApiInvoiceCreate,
} from "@/types/api";

export async function listCustomers(): Promise<ApiCustomer[]> {
  const { data } = await httpClient.get<ApiCustomer[]>(ENDPOINTS.CRM.CUSTOMERS);
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

function slugify(value: string): string {
  return (
    value
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "") || "client"
  );
}

/**
 * Resolve a customer id from a client/merchant name: find an existing customer
 * by (case-insensitive) name, otherwise create one.
 *
 * NOTE: this is a pragmatic stand-in. A proper customer picker (search +
 * select, or an explicit email field) should replace the auto-derived email —
 * tracked as a Sprint 5 follow-up.
 */
export async function resolveCustomerId(name: string): Promise<string> {
  const trimmed = name.trim();
  const existing = await listCustomers();
  const match = existing.find(
    (c) => c.name.trim().toLowerCase() === trimmed.toLowerCase()
  );
  if (match) return match.id;

  const created = await createCustomer({
    name: trimmed,
    email: `${slugify(trimmed)}@example.com`,
  });
  return created.id;
}
