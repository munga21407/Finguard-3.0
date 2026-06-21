// ─── Finance data hooks ────────────────────────────────────────────────────────
// TanStack Query hooks over the finance + CRM REST endpoints. Dashboard widgets
// consume these instead of hardcoded mock arrays. Query keys are centralised so
// mutations elsewhere (e.g. createInvoice) can invalidate the right caches.

import { useMemo } from "react";
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

// ─── Derived dashboard metrics ──────────────────────────────────────────────────
// KPI cards and trend charts are computed client-side from the invoice / expense /
// budget lists rather than from dedicated aggregate endpoints. Money fields arrive
// as Decimal strings, hence the Number() coercion. Metrics with no backend source
// (e.g. period-over-period trends, scheduled payables) are intentionally absent so
// the UI can render an honest "—" instead of a fabricated figure.

const DAY_MS = 86_400_000;
const num = (v: string | number | null | undefined): number =>
  v == null ? 0 : typeof v === "string" ? Number(v) || 0 : v;

export interface MonthBucket {
  label: string;
  value: number;
}

/**
 * Sum expense amounts into the trailing `months` calendar buckets (oldest →
 * newest), labelled by short month name. Shared by the spend/cash-flow charts.
 */
export function bucketExpensesByMonth(
  expenses: ApiExpense[],
  months: number,
): MonthBucket[] {
  const now = new Date();
  const buckets: MonthBucket[] = [];
  const index = new Map<string, number>();
  for (let i = months - 1; i >= 0; i--) {
    const d = new Date(now.getFullYear(), now.getMonth() - i, 1);
    index.set(`${d.getFullYear()}-${d.getMonth()}`, buckets.length);
    buckets.push({ label: d.toLocaleDateString("en-US", { month: "short" }), value: 0 });
  }
  for (const e of expenses) {
    const d = new Date(e.created_at);
    const idx = index.get(`${d.getFullYear()}-${d.getMonth()}`);
    if (idx !== undefined) buckets[idx].value += num(e.amount);
  }
  return buckets;
}

export interface FinanceSummary {
  /** Total cash collected against invoices (Σ amount_paid). */
  totalCollected: number;
  /** Open receivable balance (Σ balance_due on non-cancelled invoices). */
  outstanding: number;
  /** Cash collected within the current calendar month (Σ amount_paid by paid_at). */
  inflowMTD: number;
  /** Mean days between invoice creation and payment, or null if none paid. */
  avgDaysToPay: number | null;
  /** Total recorded spend (Σ expense.amount). */
  totalExpenses: number;
  /** Trailing-30-day spend — used as the monthly burn proxy. */
  burnRate30d: number;
  /** Approximate cash position: collected − spent. */
  cashBalance: number;
  /** cashBalance ÷ monthly burn, in months. null when burn is 0. */
  runwayMonths: number | null;
  /** Σ budget.amount (allocated). */
  budgetAllocated: number;
  /** Σ budget.spent. */
  budgetSpent: number;
  /** (spent − allocated) ÷ allocated × 100, or null when nothing allocated. */
  budgetVariancePct: number | null;
  /** Σ max(0, spent − allocated) across budgets. */
  projectedOverages: number;
  /** Number of budget categories whose spend exceeds their allocation. */
  overBudgetCount: number;
  /** Whole days until the latest budget period_end, or null if all elapsed. */
  budgetDaysRemaining: number | null;
  /** Fraction (0–100) of the overall budget window already elapsed, or null. */
  budgetPeriodElapsedPct: number | null;
}

/**
 * Aggregate the finance lists into the figures the dashboard KPI cards display.
 * Wraps the three underlying queries so callers get a single loading/error gate.
 */
export function useFinanceSummary(): {
  data: FinanceSummary;
  isLoading: boolean;
  isError: boolean;
} {
  const invoicesQ = useInvoices();
  const expensesQ = useExpenses();
  const budgetsQ = useBudgets();

  const data = useMemo<FinanceSummary>(() => {
    const invoices = invoicesQ.data ?? [];
    const expenses = expensesQ.data ?? [];
    const budgets = budgetsQ.data ?? [];

    const now = Date.now();
    const monthStart = (() => {
      const d = new Date();
      return new Date(d.getFullYear(), d.getMonth(), 1).getTime();
    })();

    let totalCollected = 0;
    let outstanding = 0;
    let inflowMTD = 0;
    let payDaysTotal = 0;
    let paidCount = 0;
    for (const inv of invoices) {
      totalCollected += num(inv.amount_paid);
      if (inv.status !== "cancelled") outstanding += num(inv.balance_due);
      if (inv.paid_at) {
        const paidMs = new Date(inv.paid_at).getTime();
        if (paidMs >= monthStart) inflowMTD += num(inv.amount_paid);
        payDaysTotal += (paidMs - new Date(inv.created_at).getTime()) / DAY_MS;
        paidCount += 1;
      }
    }

    let totalExpenses = 0;
    let burnRate30d = 0;
    for (const exp of expenses) {
      const amt = num(exp.amount);
      totalExpenses += amt;
      if (now - new Date(exp.created_at).getTime() <= 30 * DAY_MS) burnRate30d += amt;
    }

    let budgetAllocated = 0;
    let budgetSpent = 0;
    let projectedOverages = 0;
    let overBudgetCount = 0;
    let latestPeriodEnd = 0;
    let earliestPeriodStart = Number.POSITIVE_INFINITY;
    for (const b of budgets) {
      const allocated = num(b.amount);
      const spent = num(b.spent);
      budgetAllocated += allocated;
      budgetSpent += spent;
      if (spent > allocated) {
        projectedOverages += spent - allocated;
        overBudgetCount += 1;
      }
      latestPeriodEnd = Math.max(latestPeriodEnd, new Date(b.period_end).getTime());
      earliestPeriodStart = Math.min(earliestPeriodStart, new Date(b.period_start).getTime());
    }

    const cashBalance = totalCollected - totalExpenses;
    const budgetDaysRemaining =
      latestPeriodEnd > now ? Math.ceil((latestPeriodEnd - now) / DAY_MS) : null;
    const hasBudgetWindow =
      budgets.length > 0 && latestPeriodEnd > earliestPeriodStart;
    const budgetPeriodElapsedPct = hasBudgetWindow
      ? Math.max(
          0,
          Math.min(
            100,
            ((now - earliestPeriodStart) / (latestPeriodEnd - earliestPeriodStart)) * 100,
          ),
        )
      : null;

    return {
      totalCollected,
      outstanding,
      inflowMTD,
      avgDaysToPay: paidCount > 0 ? payDaysTotal / paidCount : null,
      totalExpenses,
      burnRate30d,
      cashBalance,
      runwayMonths: burnRate30d > 0 ? cashBalance / burnRate30d : null,
      budgetAllocated,
      budgetSpent,
      budgetVariancePct:
        budgetAllocated > 0 ? ((budgetSpent - budgetAllocated) / budgetAllocated) * 100 : null,
      projectedOverages,
      overBudgetCount,
      budgetDaysRemaining,
      budgetPeriodElapsedPct,
    };
  }, [invoicesQ.data, expensesQ.data, budgetsQ.data]);

  return {
    data,
    isLoading: invoicesQ.isLoading || expensesQ.isLoading || budgetsQ.isLoading,
    isError: invoicesQ.isError || expensesQ.isError || budgetsQ.isError,
  };
}
