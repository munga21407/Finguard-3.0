"use client";

// ─── Inventory dialogs ──────────────────────────────────────────────────────────
// Lightweight modal + the create-product / receive / issue / adjust forms. Each
// form drives a TanStack mutation from useInventory and closes on success, so the
// list, level, history, and reports refetch automatically.

import { useState, type ReactNode } from "react";
import { useAdjustStock, useCreateProduct, useRecordMovement } from "@/lib/hooks/useInventory";
import type { ApiMovementReason, ApiUnitOfMeasure } from "@/types/api";

const UNITS: ApiUnitOfMeasure[] = ["each", "kg", "litre", "metre", "box", "pack"];
const ADJUST_REASONS: ApiMovementReason[] = [
  "stock_take",
  "damage",
  "theft",
  "expiry",
  "correction",
  "other",
];

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

export function NewProductForm({ onDone }: { onDone: () => void }) {
  const create = useCreateProduct();
  const [sku, setSku] = useState("");
  const [name, setName] = useState("");
  const [category, setCategory] = useState("");
  const [unit, setUnit] = useState<ApiUnitOfMeasure>("each");
  const [costPrice, setCostPrice] = useState("0");
  const [sellingPrice, setSellingPrice] = useState("0");
  const [reorderLevel, setReorderLevel] = useState("0");
  const [reorderQuantity, setReorderQuantity] = useState("0");

  const submit = async () => {
    await create.mutateAsync({
      sku,
      name,
      category: category || null,
      unit,
      cost_price: costPrice,
      selling_price: sellingPrice,
      reorder_level: reorderLevel,
      reorder_quantity: reorderQuantity,
      is_active: true,
    });
    onDone();
  };

  return (
    <div className="space-y-3">
      <div>
        <label className={labelCls}>SKU</label>
        <input className={inputCls} value={sku} onChange={(e) => setSku(e.target.value)} />
      </div>
      <div>
        <label className={labelCls}>Name</label>
        <input className={inputCls} value={name} onChange={(e) => setName(e.target.value)} />
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className={labelCls}>Category</label>
          <input className={inputCls} value={category} onChange={(e) => setCategory(e.target.value)} />
        </div>
        <div>
          <label className={labelCls}>Unit</label>
          <select className={inputCls} value={unit} onChange={(e) => setUnit(e.target.value as ApiUnitOfMeasure)}>
            {UNITS.map((u) => (
              <option key={u} value={u}>
                {u}
              </option>
            ))}
          </select>
        </div>
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className={labelCls}>Cost price</label>
          <input className={inputCls} value={costPrice} onChange={(e) => setCostPrice(e.target.value)} />
        </div>
        <div>
          <label className={labelCls}>Selling price</label>
          <input className={inputCls} value={sellingPrice} onChange={(e) => setSellingPrice(e.target.value)} />
        </div>
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className={labelCls}>Reorder level</label>
          <input className={inputCls} value={reorderLevel} onChange={(e) => setReorderLevel(e.target.value)} />
        </div>
        <div>
          <label className={labelCls}>Reorder qty</label>
          <input
            className={inputCls}
            value={reorderQuantity}
            onChange={(e) => setReorderQuantity(e.target.value)}
          />
        </div>
      </div>
      {create.isError && <p className="text-xs text-lf-error">Could not create product.</p>}
      <button className={btnCls} disabled={!sku || !name || create.isPending} onClick={submit}>
        {create.isPending ? "Creating…" : "Create product"}
      </button>
    </div>
  );
}

export function MovementForm({
  productId,
  mode,
  onDone,
}: {
  productId: string;
  mode: "receive" | "issue";
  onDone: () => void;
}) {
  const record = useRecordMovement(productId);
  const [quantity, setQuantity] = useState("");
  const [unitCost, setUnitCost] = useState("");
  const [note, setNote] = useState("");

  const submit = async () => {
    await record.mutateAsync({
      movement_type: mode === "receive" ? "receipt" : "issue",
      quantity,
      unit_cost: mode === "receive" ? unitCost : null,
      reason: mode === "receive" ? "purchase" : null,
      note: note || null,
    });
    onDone();
  };

  return (
    <div className="space-y-3">
      <div>
        <label className={labelCls}>Quantity</label>
        <input className={inputCls} value={quantity} onChange={(e) => setQuantity(e.target.value)} />
      </div>
      {mode === "receive" && (
        <div>
          <label className={labelCls}>Unit cost</label>
          <input className={inputCls} value={unitCost} onChange={(e) => setUnitCost(e.target.value)} />
        </div>
      )}
      <div>
        <label className={labelCls}>Note (optional)</label>
        <input className={inputCls} value={note} onChange={(e) => setNote(e.target.value)} />
      </div>
      {record.isError && (
        <p className="text-xs text-lf-error">
          {mode === "issue" ? "Rejected — likely insufficient stock." : "Could not record receipt."}
        </p>
      )}
      <button
        className={btnCls}
        disabled={!quantity || (mode === "receive" && !unitCost) || record.isPending}
        onClick={submit}
      >
        {record.isPending ? "Saving…" : mode === "receive" ? "Receive stock" : "Issue stock"}
      </button>
    </div>
  );
}

export function AdjustForm({ productId, onDone }: { productId: string; onDone: () => void }) {
  const adjust = useAdjustStock(productId);
  const [quantity, setQuantity] = useState("");
  const [reason, setReason] = useState<ApiMovementReason>("stock_take");
  const [note, setNote] = useState("");

  const submit = async () => {
    await adjust.mutateAsync({ quantity, reason, note: note || null });
    onDone();
  };

  return (
    <div className="space-y-3">
      <div>
        <label className={labelCls}>Signed quantity (negative writes stock off)</label>
        <input
          className={inputCls}
          value={quantity}
          placeholder="e.g. -3 or 5"
          onChange={(e) => setQuantity(e.target.value)}
        />
      </div>
      <div>
        <label className={labelCls}>Reason</label>
        <select
          className={inputCls}
          value={reason}
          onChange={(e) => setReason(e.target.value as ApiMovementReason)}
        >
          {ADJUST_REASONS.map((r) => (
            <option key={r} value={r}>
              {r.replace("_", " ")}
            </option>
          ))}
        </select>
      </div>
      <div>
        <label className={labelCls}>Note (optional)</label>
        <input className={inputCls} value={note} onChange={(e) => setNote(e.target.value)} />
      </div>
      {adjust.isError && <p className="text-xs text-lf-error">Adjustment rejected.</p>}
      <button
        className={btnCls}
        disabled={!quantity || quantity === "0" || adjust.isPending}
        onClick={submit}
      >
        {adjust.isPending ? "Saving…" : "Apply adjustment"}
      </button>
    </div>
  );
}
