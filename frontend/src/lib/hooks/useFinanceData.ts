// ─── Finance data hooks ────────────────────────────────────────────────────────
// TanStack Query hooks over the finance + CRM REST endpoints. Dashboard widgets
// consume these instead of hardcoded mock arrays. Query keys are centralised so
// mutations elsewhere (e.g. createInvoice) can invalidate the right caches.

import { useQuery } from "@tanstack/react-query";
import {
  listBudgets,
  listCustomers,
  listExpenses,
  listInvoices,
} from "@/lib/api/finance";
import type {
  ApiBudget,
  ApiCustomer,
  ApiExpense,
  ApiInvoice,
} from "@/types/api";

export const financeKeys = {
  invoices: ["finance", "invoices"] as const,
  expenses: ["finance", "expenses"] as const,
  budgets: ["finance", "budgets"] as const,
  customers: ["crm", "customers"] as const,
};

export function useInvoices() {
  return useQuery<ApiInvoice[]>({
    queryKey: financeKeys.invoices,
    queryFn: listInvoices,
  });
}

export function useExpenses() {
  return useQuery<ApiExpense[]>({
    queryKey: financeKeys.expenses,
    queryFn: listExpenses,
  });
}

export function useBudgets() {
  return useQuery<ApiBudget[]>({
    queryKey: financeKeys.budgets,
    queryFn: listBudgets,
  });
}

export function useCustomers() {
  return useQuery<ApiCustomer[]>({
    queryKey: financeKeys.customers,
    queryFn: listCustomers,
  });
}
