"use client";

// ─── Customers (CRM) ────────────────────────────────────────────────────────────
// Customer management surface over /api/v1/crm — a searchable list with status
// KPIs, a detail panel (fetched fresh by id), and create/edit dialogs. All data
// comes from live TanStack Query hooks — no mock data. Writes are gated to
// crm:write (ACCOUNTANT+); VIEWERs get read-only access, matching the backend RBAC.

import { useMemo, useState } from "react";
import { KpiCard } from "@/components/dashboard/KpiCard";
import { CustomerDetailPanel, StatusBadge } from "@/components/dashboard/customers/CustomerDetailPanel";
import { Modal, NewCustomerForm } from "@/components/dashboard/customers/CustomerDialogs";
import { QueryState } from "@/components/ui/QueryState";
import { useCustomers } from "@/lib/hooks/useFinanceData";
import { useRole } from "@/lib/hooks/useRole";

export default function CustomersPage() {
  const customers = useCustomers();
  const { hasRole } = useRole();
  const canWrite = hasRole("ACCOUNTANT");

  const [selected, setSelected] = useState<string | null>(null);
  const [showNew, setShowNew] = useState(false);
  const [query, setQuery] = useState("");

  const list = useMemo(() => customers.data ?? [], [customers.data]);

  const counts = useMemo(() => {
    let active = 0;
    let prospects = 0;
    for (const c of list) {
      if (c.status === "active") active += 1;
      else if (c.status === "prospect") prospects += 1;
    }
    return { total: list.length, active, prospects };
  }, [list]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return list;
    return list.filter(
      (c) => c.name.toLowerCase().includes(q) || c.email.toLowerCase().includes(q),
    );
  }, [list, query]);

  return (
    <div className="space-y-6 p-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-lf-on-surface">Customers</h1>
          <p className="text-sm text-lf-on-surface-variant">
            Manage your client directory — the CRM records that feed invoicing and the AI advisor.
          </p>
        </div>
        {canWrite && (
          <button
            onClick={() => setShowNew(true)}
            className="rounded-lg bg-lf-primary px-4 py-2 text-sm font-semibold text-lf-on-primary hover:opacity-90"
          >
            New customer
          </button>
        )}
      </div>

      <div className="grid gap-4 sm:grid-cols-3">
        <KpiCard title="Customers" value={customers.data ? String(counts.total) : "—"} />
        <KpiCard title="Active" value={customers.data ? String(counts.active) : "—"} />
        <KpiCard title="Prospects" value={customers.data ? String(counts.prospects) : "—"} />
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <div className="rounded-xl border border-lf-outline-variant/10 bg-lf-surface-container-lowest p-4">
          <div className="mb-3 flex items-center justify-between gap-3">
            <h2 className="text-sm font-semibold text-lf-on-surface">Directory</h2>
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search name or email…"
              className="h-9 w-48 rounded-lg border border-lf-outline-variant/40 bg-lf-surface px-3 text-sm text-lf-on-surface focus:border-lf-primary focus:outline-none"
            />
          </div>
          <QueryState
            isLoading={customers.isLoading}
            isError={customers.isError}
            isEmpty={list.length === 0}
            emptyLabel="No customers yet — add your first one."
            onRetry={customers.refetch}
          >
            {filtered.length === 0 ? (
              <p className="px-1 py-4 text-sm text-lf-on-surface-variant">No matching customers.</p>
            ) : (
              <ul className="space-y-2">
                {filtered.map((c) => (
                  <li key={c.id}>
                    <button
                      onClick={() => setSelected(c.id)}
                      className={`flex w-full items-center justify-between gap-2 rounded-lg border p-3 text-left transition-colors ${
                        selected === c.id
                          ? "border-lf-primary bg-lf-surface"
                          : "border-lf-outline-variant/20 hover:border-lf-primary/50"
                      }`}
                    >
                      <div className="min-w-0">
                        <div className="truncate font-medium text-lf-on-surface">{c.name}</div>
                        <div className="truncate text-xs text-lf-on-surface-variant">{c.email}</div>
                      </div>
                      <StatusBadge status={c.status} />
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </QueryState>
        </div>

        <div>
          {selected ? (
            <CustomerDetailPanel customerId={selected} canWrite={canWrite} />
          ) : (
            <div className="flex h-full min-h-40 items-center justify-center rounded-xl border border-dashed border-lf-outline-variant/30 text-sm text-lf-on-surface-variant">
              Select a customer to view their profile.
            </div>
          )}
        </div>
      </div>

      {showNew && (
        <Modal title="New customer" onClose={() => setShowNew(false)}>
          <NewCustomerForm
            onDone={(id) => {
              if (id) setSelected(id);
              setShowNew(false);
            }}
          />
        </Modal>
      )}
    </div>
  );
}
