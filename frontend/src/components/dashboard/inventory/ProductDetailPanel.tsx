"use client";

// ─── Product detail panel ───────────────────────────────────────────────────────
// Current stock level + the append-only movement ledger for one product, with
// receive / issue / adjust actions. All data is live via useInventory hooks.

import { useState } from "react";
import { QueryState } from "@/components/ui/QueryState";
import { useMovements, useProduct, useStockLevel } from "@/lib/hooks/useInventory";
import { AdjustForm, Modal, MovementForm } from "./InventoryDialogs";

type Dialog = "receive" | "issue" | "adjust" | null;

const actionCls =
  "rounded-lg border border-lf-outline-variant/40 px-3 py-1.5 text-xs font-semibold " +
  "text-lf-on-surface hover:border-lf-primary hover:text-lf-primary";

export function ProductDetailPanel({ productId }: { productId: string }) {
  const product = useProduct(productId);
  const level = useStockLevel(productId);
  const movements = useMovements(productId);
  const [dialog, setDialog] = useState<Dialog>(null);

  const onHand = level.data ? Number(level.data.quantity_on_hand) : 0;
  const reorder = product.data ? Number(product.data.reorder_level) : 0;
  const low = reorder > 0 && onHand <= reorder;

  return (
    <div className="rounded-xl border border-lf-outline-variant/10 bg-lf-surface-container-lowest p-6">
      <QueryState isLoading={product.isLoading} isError={product.isError}>
        <div className="mb-4 flex items-start justify-between">
          <div>
            <h2 className="text-lg font-semibold text-lf-on-surface">{product.data?.name}</h2>
            <p className="text-sm text-lf-on-surface-variant">SKU {product.data?.sku}</p>
          </div>
          <div className="flex gap-2">
            <button className={actionCls} onClick={() => setDialog("receive")}>
              Receive
            </button>
            <button className={actionCls} onClick={() => setDialog("issue")}>
              Issue
            </button>
            <button className={actionCls} onClick={() => setDialog("adjust")}>
              Adjust
            </button>
          </div>
        </div>

        <div className="mb-6 grid grid-cols-3 gap-4">
          <Stat label="On hand" value={String(onHand)} highlight={low ? "low" : undefined} />
          <Stat label="Avg cost" value={level.data ? level.data.average_cost : "—"} />
          <Stat label="Reorder level" value={product.data ? product.data.reorder_level : "—"} />
        </div>

        <h3 className="mb-2 text-xs font-semibold uppercase tracking-widest text-lf-on-surface-variant">
          Movement history
        </h3>
        <QueryState
          isLoading={movements.isLoading}
          isError={movements.isError}
          isEmpty={movements.data?.length === 0}
          emptyLabel="No movements yet."
        >
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-lf-on-surface-variant">
                  <th className="py-2 pr-4">#</th>
                  <th className="py-2 pr-4">Type</th>
                  <th className="py-2 pr-4">Qty</th>
                  <th className="py-2 pr-4">Balance</th>
                  <th className="py-2 pr-4">Reason</th>
                  <th className="py-2">When</th>
                </tr>
              </thead>
              <tbody>
                {movements.data?.map((m) => (
                  <tr key={m.id} className="border-t border-lf-outline-variant/10">
                    <td className="py-2 pr-4 text-lf-on-surface-variant">{m.sequence}</td>
                    <td className="py-2 pr-4 font-medium capitalize">{m.movement_type}</td>
                    <td className="py-2 pr-4">{m.quantity}</td>
                    <td className="py-2 pr-4">{m.balance_after}</td>
                    <td className="py-2 pr-4 capitalize text-lf-on-surface-variant">
                      {m.movement_reason ?? "—"}
                    </td>
                    <td className="py-2 text-lf-on-surface-variant">
                      {new Date(m.occurred_at).toLocaleString()}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </QueryState>
      </QueryState>

      {dialog === "receive" && (
        <Modal title="Receive stock" onClose={() => setDialog(null)}>
          <MovementForm productId={productId} mode="receive" onDone={() => setDialog(null)} />
        </Modal>
      )}
      {dialog === "issue" && (
        <Modal title="Issue stock" onClose={() => setDialog(null)}>
          <MovementForm productId={productId} mode="issue" onDone={() => setDialog(null)} />
        </Modal>
      )}
      {dialog === "adjust" && (
        <Modal title="Stock-take adjustment" onClose={() => setDialog(null)}>
          <AdjustForm productId={productId} onDone={() => setDialog(null)} />
        </Modal>
      )}
    </div>
  );
}

function Stat({ label, value, highlight }: { label: string; value: string; highlight?: "low" }) {
  return (
    <div className="rounded-lg bg-lf-surface p-3">
      <div className="text-[10px] font-semibold uppercase tracking-widest text-lf-on-surface-variant">
        {label}
      </div>
      <div
        className={`mt-1 text-xl font-bold ${
          highlight === "low" ? "text-lf-error" : "text-lf-on-surface"
        }`}
      >
        {value}
      </div>
    </div>
  );
}
