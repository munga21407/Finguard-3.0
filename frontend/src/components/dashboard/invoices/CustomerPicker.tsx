"use client";

// ─── CustomerPicker ─────────────────────────────────────────────────────────────
// Searchable combobox over /crm/customers. Lets the user pick an existing
// customer or create a new one with EXPLICIT name + email + type — replacing the
// old resolveCustomerId() that silently invented an `@example.com` email.
//
// Emits the selected customer id (and name) to the parent. New customers are
// created via the CRM endpoint and the customers query cache is invalidated so
// every consumer (dashboard tables, this picker) sees the addition immediately.

import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Check, ChevronDown, Loader2, Plus, Search, UserPlus } from "lucide-react";
import { cn } from "@/lib/utils/cn";
import { createCustomer } from "@/lib/api/finance";
import { financeKeys, useCustomers } from "@/lib/hooks/useFinanceData";
import type { ApiCustomer, ApiCustomerType } from "@/types/api";

interface CustomerPickerProps {
  value: string | null;            // selected customer id
  onChange: (id: string | null, name: string) => void;
  /** Name extracted by Agent A — used to prefill the search and auto-select on exact match. */
  prefillName?: string;
  error?: string;
  inputClassName?: string;
}

export function CustomerPicker({
  value,
  onChange,
  prefillName,
  error,
  inputClassName,
}: CustomerPickerProps) {
  const { data: customers, isLoading } = useCustomers();
  const queryClient = useQueryClient();

  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [creating, setCreating] = useState(false);
  const [newEmail, setNewEmail] = useState("");
  const [newType, setNewType] = useState<ApiCustomerType>("business");
  const [createError, setCreateError] = useState<string | null>(null);
  // Remember the chosen name directly so the trigger label survives a stale
  // customers cache (e.g. immediately after creating a brand-new client, before
  // the list query has refetched).
  const [pickedLabel, setPickedLabel] = useState("");
  const containerRef = useRef<HTMLDivElement>(null);

  const selected = useMemo(
    () => (customers ?? []).find((c) => c.id === value) ?? null,
    [customers, value]
  );
  const displayLabel = selected?.name || pickedLabel;

  // Centralise selection so onChange + the local label stay in sync.
  const select = (id: string | null, name: string) => {
    setPickedLabel(name);
    onChange(id, name);
  };

  // Clear the remembered label when the parent resets the selection.
  useEffect(() => {
    if (!value) setPickedLabel("");
  }, [value]);

  // Auto-select an existing customer when Agent A's extracted name matches one
  // exactly (case-insensitive). Never auto-creates — that stays an explicit act.
  useEffect(() => {
    if (!prefillName || value || !customers) return;
    const match = customers.find(
      (c) => c.name.trim().toLowerCase() === prefillName.trim().toLowerCase()
    );
    if (match) {
      select(match.id, match.name);
    } else {
      setQuery(prefillName);
    }
    // `select` is stable enough for this effect's intent; deps mirror inputs.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [prefillName, value, customers]);

  // Close on outside click.
  useEffect(() => {
    function onDocClick(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    if (open) document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, [open]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    const list = customers ?? [];
    if (!q) return list.slice(0, 50);
    return list.filter((c) => c.name.toLowerCase().includes(q) || c.email.toLowerCase().includes(q)).slice(0, 50);
  }, [customers, query]);

  const createMutation = useMutation({
    mutationFn: (body: { name: string; email: string; customer_type: ApiCustomerType }) =>
      createCustomer(body),
    onSuccess: (created: ApiCustomer) => {
      queryClient.invalidateQueries({ queryKey: financeKeys.customers });
      select(created.id, created.name);
      resetCreate();
      setOpen(false);
    },
    onError: () => setCreateError("Could not create customer. Check the email is unique and valid."),
  });

  function resetCreate() {
    setCreating(false);
    setNewEmail("");
    setNewType("business");
    setCreateError(null);
  }

  function pick(c: ApiCustomer) {
    select(c.id, c.name);
    setOpen(false);
  }

  function submitNew() {
    const name = query.trim();
    if (!name) {
      setCreateError("Enter a customer name.");
      return;
    }
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(newEmail.trim())) {
      setCreateError("Enter a valid email address.");
      return;
    }
    setCreateError(null);
    createMutation.mutate({ name, email: newEmail.trim(), customer_type: newType });
  }

  return (
    <div className="relative" ref={containerRef}>
      {/* Trigger */}
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        data-testid="customer-picker-trigger"
        className={cn(
          "w-full h-10 rounded-lg border px-3 text-sm text-left flex items-center justify-between gap-2 bg-lf-surface-container-low transition-all",
          "focus:outline-none focus:ring-2 focus:ring-lf-primary/20 focus:border-lf-primary",
          error ? "border-lf-error bg-lf-error-container/10" : "border-lf-outline-variant/30",
          inputClassName
        )}
      >
        <span className={cn("truncate", displayLabel ? "text-lf-on-surface" : "text-lf-on-surface-variant/60")}>
          {displayLabel || "Select or create a client…"}
        </span>
        <ChevronDown size={15} className="text-lf-on-surface-variant shrink-0" />
      </button>

      {/* Dropdown */}
      {open && (
        <div className="absolute z-20 mt-1 w-full rounded-xl border border-lf-outline-variant/30 bg-lf-surface-container-lowest shadow-lg overflow-hidden">
          {/* Search */}
          <div className="flex items-center gap-2 px-3 py-2 border-b border-lf-outline-variant/20">
            <Search size={14} className="text-lf-on-surface-variant shrink-0" />
            <input
              autoFocus
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search clients…"
              data-testid="customer-picker-search"
              className="w-full bg-transparent text-sm text-lf-on-surface focus:outline-none placeholder:text-lf-on-surface-variant/50"
            />
          </div>

          {/* List */}
          <div className="max-h-56 overflow-y-auto">
            {isLoading && (
              <div className="px-3 py-4 text-xs text-lf-on-surface-variant flex items-center gap-2">
                <Loader2 size={13} className="animate-spin" /> Loading clients…
              </div>
            )}
            {!isLoading && filtered.map((c) => (
              <button
                key={c.id}
                type="button"
                onClick={() => pick(c)}
                className="w-full px-3 py-2.5 text-left flex items-center justify-between gap-2 hover:bg-lf-surface-container-low transition-colors"
              >
                <span className="flex flex-col min-w-0">
                  <span className="text-sm font-medium text-lf-on-surface truncate">{c.name}</span>
                  <span className="text-[11px] text-lf-on-surface-variant truncate">{c.email}</span>
                </span>
                {c.id === value && <Check size={14} className="text-lf-primary shrink-0" />}
              </button>
            ))}
            {!isLoading && filtered.length === 0 && !creating && (
              <p className="px-3 py-3 text-xs text-lf-on-surface-variant">No matching clients.</p>
            )}
          </div>

          {/* Create new */}
          <div className="border-t border-lf-outline-variant/20">
            {!creating ? (
              <button
                type="button"
                onClick={() => setCreating(true)}
                data-testid="customer-picker-create-toggle"
                className="w-full px-3 py-2.5 flex items-center gap-2 text-sm font-semibold text-lf-primary hover:bg-lf-primary-fixed/10 transition-colors"
              >
                <Plus size={14} />
                Create {query.trim() ? `"${query.trim()}"` : "new client"}
              </button>
            ) : (
              <div className="p-3 flex flex-col gap-2 bg-lf-surface-container-low/40">
                <div className="flex items-center gap-2 text-xs font-bold text-lf-on-surface">
                  <UserPlus size={13} /> New client
                </div>
                <input
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="Client name"
                  data-testid="customer-picker-new-name"
                  className="w-full h-9 rounded-lg border border-lf-outline-variant/30 px-3 text-sm bg-lf-surface-container-lowest focus:outline-none focus:ring-2 focus:ring-lf-primary/20"
                />
                <input
                  type="email"
                  value={newEmail}
                  onChange={(e) => setNewEmail(e.target.value)}
                  placeholder="client@company.com"
                  data-testid="customer-picker-new-email"
                  className="w-full h-9 rounded-lg border border-lf-outline-variant/30 px-3 text-sm bg-lf-surface-container-lowest focus:outline-none focus:ring-2 focus:ring-lf-primary/20"
                />
                <div className="flex items-center gap-2">
                  <select
                    value={newType}
                    onChange={(e) => setNewType(e.target.value as ApiCustomerType)}
                    className="h-9 rounded-lg border border-lf-outline-variant/30 px-2 text-sm bg-lf-surface-container-lowest focus:outline-none"
                  >
                    <option value="business">Business</option>
                    <option value="individual">Individual</option>
                  </select>
                  <button
                    type="button"
                    onClick={submitNew}
                    disabled={createMutation.isPending}
                    data-testid="customer-picker-new-submit"
                    className="flex-1 h-9 rounded-lg bg-lf-primary text-lf-on-primary text-sm font-bold flex items-center justify-center gap-1.5 hover:bg-lf-secondary disabled:opacity-60 transition-colors"
                  >
                    {createMutation.isPending ? <Loader2 size={13} className="animate-spin" /> : <Check size={13} />}
                    Add
                  </button>
                  <button
                    type="button"
                    onClick={resetCreate}
                    className="h-9 px-3 rounded-lg border border-lf-outline-variant/30 text-sm text-lf-on-surface-variant hover:bg-lf-surface-container-low transition-colors"
                  >
                    Cancel
                  </button>
                </div>
                {createError && <p className="text-[11px] text-lf-error">{createError}</p>}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
