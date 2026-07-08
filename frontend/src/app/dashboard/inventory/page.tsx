"use client";

// ─── Stock Management ───────────────────────────────────────────────────────────
// Live product list with on-hand + low-stock badges, an inventory-valuation KPI,
// and a detail panel (stock level + movement history + receive/issue/adjust). All
// data comes from live TanStack Query hooks — no mock data.

import { useMemo, useState } from "react";
import { KpiCard } from "@/components/dashboard/KpiCard";
import { Modal, NewProductForm } from "@/components/dashboard/inventory/InventoryDialogs";
import { ProductDetailPanel } from "@/components/dashboard/inventory/ProductDetailPanel";
import { QueryState } from "@/components/ui/QueryState";
import { useLevels, useLowStock, useProducts, useValuation } from "@/lib/hooks/useInventory";

export default function InventoryPage() {
  const products = useProducts();
  const levels = useLevels();
  const valuation = useValuation();
  const lowStock = useLowStock();
  const [selected, setSelected] = useState<string | null>(null);
  const [showNew, setShowNew] = useState(false);

  const onHandById = useMemo(() => {
    const map = new Map<string, string>();
    for (const l of levels.data ?? []) map.set(l.product_id, l.quantity_on_hand);
    return map;
  }, [levels.data]);

  const lowIds = useMemo(
    () => new Set((lowStock.data ?? []).map((i) => i.product_id)),
    [lowStock.data],
  );

  return (
    <div className="space-y-6 p-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-lf-on-surface">Stock Management</h1>
          <p className="text-sm text-lf-on-surface-variant">
            Track inventory levels, movement history, and reorder alerts.
          </p>
        </div>
        <button
          onClick={() => setShowNew(true)}
          className="rounded-lg bg-lf-primary px-4 py-2 text-sm font-semibold text-lf-on-primary hover:opacity-90"
        >
          New product
        </button>
      </div>

      <div className="grid gap-4 sm:grid-cols-3">
        <KpiCard
          title="Inventory value"
          value={valuation.data ? `KES ${valuation.data.total_value}` : "—"}
          subtext="Σ on-hand × avg cost"
        />
        <KpiCard title="Products" value={String(products.data?.length ?? "—")} />
        <KpiCard
          title="Low stock"
          value={String(lowStock.data?.length ?? "—")}
          urgentBadge={lowStock.data && lowStock.data.length > 0 ? { label: "Reorder" } : undefined}
        />
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <div className="rounded-xl border border-lf-outline-variant/10 bg-lf-surface-container-lowest p-4">
          <h2 className="mb-3 text-sm font-semibold text-lf-on-surface">Products</h2>
          <QueryState
            isLoading={products.isLoading}
            isError={products.isError}
            isEmpty={products.data?.length === 0}
            emptyLabel="No products yet — add your first one."
            onRetry={products.refetch}
          >
            <ul className="space-y-2">
              {products.data?.map((p) => {
                const isLow = lowIds.has(p.id);
                return (
                  <li key={p.id}>
                    <button
                      onClick={() => setSelected(p.id)}
                      className={`flex w-full items-center justify-between rounded-lg border p-3 text-left transition-colors ${
                        selected === p.id
                          ? "border-lf-primary bg-lf-surface"
                          : "border-lf-outline-variant/20 hover:border-lf-primary/50"
                      }`}
                    >
                      <div>
                        <div className="font-medium text-lf-on-surface">{p.name}</div>
                        <div className="text-xs text-lf-on-surface-variant">SKU {p.sku}</div>
                      </div>
                      <div className="flex items-center gap-2">
                        <span className="text-sm text-lf-on-surface-variant">
                          {onHandById.get(p.id) ?? "0"} on hand
                        </span>
                        {isLow && (
                          <span className="rounded-full bg-lf-error-container px-2 py-0.5 text-[10px] font-bold text-lf-on-error-container">
                            Low
                          </span>
                        )}
                      </div>
                    </button>
                  </li>
                );
              })}
            </ul>
          </QueryState>
        </div>

        <div>
          {selected ? (
            <ProductDetailPanel productId={selected} />
          ) : (
            <div className="flex h-full min-h-40 items-center justify-center rounded-xl border border-dashed border-lf-outline-variant/30 text-sm text-lf-on-surface-variant">
              Select a product to view its stock level and history.
            </div>
          )}
        </div>
      </div>

      {showNew && (
        <Modal title="New product" onClose={() => setShowNew(false)}>
          <NewProductForm onDone={() => setShowNew(false)} />
        </Modal>
      )}
    </div>
  );
}
