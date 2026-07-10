"use client";

// ─── Customer dialogs ───────────────────────────────────────────────────────────
// Lightweight modal + the create / edit customer forms. Each form drives a
// TanStack mutation from useFinanceData and closes on success, so the customer
// list and the open detail panel refetch automatically. Mirrors the shape of the
// inventory dialogs (local Modal, shared input classes).

import { useState, type ReactNode } from "react";
import { useCreateCustomer, useUpdateCustomer } from "@/lib/hooks/useFinanceData";
import type {
  ApiCustomer,
  ApiCustomerStatus,
  ApiCustomerType,
} from "@/types/api";

const TYPES: ApiCustomerType[] = ["business", "individual"];
const STATUSES: ApiCustomerStatus[] = ["active", "prospect", "inactive", "churned"];

export function Modal({
  title,
  onClose,
  children,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
}) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-md rounded-xl bg-lf-surface-container-lowest p-6 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-lf-on-surface">{title}</h2>
          <button onClick={onClose} className="text-lf-outline hover:text-lf-primary" aria-label="Close">
            ✕
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

const inputCls =
  "w-full rounded-lg border border-lf-outline-variant/40 bg-lf-surface px-3 py-2 text-sm " +
  "text-lf-on-surface focus:border-lf-primary focus:outline-none";
const labelCls = "block text-xs font-semibold text-lf-on-surface-variant mb-1";
const btnCls =
  "w-full rounded-lg bg-lf-primary px-4 py-2 text-sm font-semibold text-lf-on-primary " +
  "hover:opacity-90 disabled:opacity-50";

const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

export function NewCustomerForm({ onDone }: { onDone: (createdId?: string) => void }) {
  const create = useCreateCustomer();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [type, setType] = useState<ApiCustomerType>("business");
  const [notes, setNotes] = useState("");
  const [localError, setLocalError] = useState<string | null>(null);

  const submit = async () => {
    if (!name.trim()) {
      setLocalError("Enter a customer name.");
      return;
    }
    if (!EMAIL_RE.test(email.trim())) {
      setLocalError("Enter a valid email address.");
      return;
    }
    setLocalError(null);
    const created = await create.mutateAsync({
      name: name.trim(),
      email: email.trim(),
      phone: phone.trim() || null,
      customer_type: type,
      notes: notes.trim() || null,
    });
    onDone(created.id);
  };

  return (
    <div className="space-y-3">
      <div>
        <label className={labelCls}>Name</label>
        <input className={inputCls} value={name} onChange={(e) => setName(e.target.value)} />
      </div>
      <div>
        <label className={labelCls}>Email</label>
        <input
          type="email"
          className={inputCls}
          value={email}
          placeholder="client@company.com"
          onChange={(e) => setEmail(e.target.value)}
        />
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className={labelCls}>Phone</label>
          <input className={inputCls} value={phone} onChange={(e) => setPhone(e.target.value)} />
        </div>
        <div>
          <label className={labelCls}>Type</label>
          <select
            className={inputCls}
            value={type}
            onChange={(e) => setType(e.target.value as ApiCustomerType)}
          >
            {TYPES.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </div>
      </div>
      <div>
        <label className={labelCls}>Notes (optional)</label>
        <input className={inputCls} value={notes} onChange={(e) => setNotes(e.target.value)} />
      </div>
      {(localError || create.isError) && (
        <p className="text-xs text-lf-error">
          {localError ?? "Could not create customer. Check the email is unique and valid."}
        </p>
      )}
      <button className={btnCls} disabled={!name || !email || create.isPending} onClick={submit}>
        {create.isPending ? "Creating…" : "Create customer"}
      </button>
    </div>
  );
}

export function EditCustomerForm({
  customer,
  onDone,
}: {
  customer: ApiCustomer;
  onDone: () => void;
}) {
  const update = useUpdateCustomer();
  const [name, setName] = useState(customer.name);
  const [phone, setPhone] = useState(customer.phone ?? "");
  const [status, setStatus] = useState<ApiCustomerStatus>(customer.status);
  const [notes, setNotes] = useState(customer.notes ?? "");
  const [localError, setLocalError] = useState<string | null>(null);

  const submit = async () => {
    if (!name.trim()) {
      setLocalError("Name cannot be empty.");
      return;
    }
    setLocalError(null);
    await update.mutateAsync({
      id: customer.id,
      body: {
        name: name.trim(),
        phone: phone.trim() || null,
        status,
        notes: notes.trim() || null,
      },
    });
    onDone();
  };

  return (
    <div className="space-y-3">
      <div>
        <label className={labelCls}>Name</label>
        <input className={inputCls} value={name} onChange={(e) => setName(e.target.value)} />
      </div>
      {/* Email + type are immutable server-side (not in CustomerUpdate) — shown read-only. */}
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className={labelCls}>Email (fixed)</label>
          <input className={`${inputCls} opacity-60`} value={customer.email} disabled readOnly />
        </div>
        <div>
          <label className={labelCls}>Phone</label>
          <input className={inputCls} value={phone} onChange={(e) => setPhone(e.target.value)} />
        </div>
      </div>
      <div>
        <label className={labelCls}>Status</label>
        <select
          className={inputCls}
          value={status}
          onChange={(e) => setStatus(e.target.value as ApiCustomerStatus)}
        >
          {STATUSES.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
      </div>
      <div>
        <label className={labelCls}>Notes (optional)</label>
        <input className={inputCls} value={notes} onChange={(e) => setNotes(e.target.value)} />
      </div>
      {(localError || update.isError) && (
        <p className="text-xs text-lf-error">{localError ?? "Could not save changes."}</p>
      )}
      <button className={btnCls} disabled={!name || update.isPending} onClick={submit}>
        {update.isPending ? "Saving…" : "Save changes"}
      </button>
    </div>
  );
}
