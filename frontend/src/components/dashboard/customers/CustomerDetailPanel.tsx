"use client";

// ─── Customer detail panel ──────────────────────────────────────────────────────
// Full profile for one customer, fetched fresh from GET /crm/customers/{id}, with
// an Edit action (gated to crm:write — ACCOUNTANT and above). The CRM profile this
// surfaces is the same record Agents H (advisor) and J (summariser, via
// preferred_locale) read when personalising their output.

import { useState } from "react";
import { QueryState } from "@/components/ui/QueryState";
import { useCustomer } from "@/lib/hooks/useFinanceData";
import type { ApiCustomerStatus } from "@/types/api";
import { EditCustomerForm, Modal } from "./CustomerDialogs";

const STATUS_STYLES: Record<ApiCustomerStatus, string> = {
  active: "bg-[#dcfce7] text-[#166534]",
  prospect: "bg-lf-secondary-fixed/40 text-lf-primary",
  inactive: "bg-lf-surface-container text-lf-on-surface-variant",
  churned: "bg-lf-error-container text-lf-on-error-container",
};

export function StatusBadge({ status }: { status: ApiCustomerStatus }) {
  return (
    <span
      className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-[10px] font-bold uppercase tracking-wide ${STATUS_STYLES[status]}`}
    >
      {status}
    </span>
  );
}

export function CustomerDetailPanel({
  customerId,
  canWrite,
}: {
  customerId: string;
  canWrite: boolean;
}) {
  const customer = useCustomer(customerId);
  const [editing, setEditing] = useState(false);

  return (
    <div className="rounded-xl border border-lf-outline-variant/10 bg-lf-surface-container-lowest p-6">
      <QueryState isLoading={customer.isLoading} isError={customer.isError} onRetry={customer.refetch}>
        {customer.data && (
          <>
            <div className="mb-4 flex items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <h2 className="truncate text-lg font-semibold text-lf-on-surface">
                    {customer.data.name}
                  </h2>
                  <StatusBadge status={customer.data.status} />
                </div>
                <p className="truncate text-sm text-lf-on-surface-variant">{customer.data.email}</p>
              </div>
              {canWrite && (
                <button
                  className="shrink-0 rounded-lg border border-lf-outline-variant/40 px-3 py-1.5 text-xs font-semibold text-lf-on-surface hover:border-lf-primary hover:text-lf-primary"
                  onClick={() => setEditing(true)}
                >
                  Edit
                </button>
              )}
            </div>

            <dl className="grid grid-cols-2 gap-4">
              <Field label="Type" value={customer.data.customer_type} />
              <Field label="Phone" value={customer.data.phone ?? "—"} />
              <Field label="Locale" value={customer.data.preferred_locale ?? "—"} />
              <Field
                label="Customer since"
                value={new Date(customer.data.created_at).toLocaleDateString()}
              />
            </dl>

            <div className="mt-4">
              <div className="text-[10px] font-semibold uppercase tracking-widest text-lf-on-surface-variant">
                Notes
              </div>
              <p className="mt-1 whitespace-pre-wrap text-sm text-lf-on-surface">
                {customer.data.notes?.trim() || "—"}
              </p>
            </div>

            {editing && (
              <Modal title="Edit customer" onClose={() => setEditing(false)}>
                <EditCustomerForm customer={customer.data} onDone={() => setEditing(false)} />
              </Modal>
            )}
          </>
        )}
      </QueryState>
    </div>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg bg-lf-surface p-3">
      <dt className="text-[10px] font-semibold uppercase tracking-widest text-lf-on-surface-variant">
        {label}
      </dt>
      <dd className="mt-1 text-sm font-medium capitalize text-lf-on-surface">{value}</dd>
    </div>
  );
}
