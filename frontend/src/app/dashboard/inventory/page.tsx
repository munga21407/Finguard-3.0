"use client";

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
  const [selectedProductId, setSelectedProductId] = useState<string | null>(null);
  const [showNew, setShowNew] = useState(false);

  const onHandById = useMemo(() => {
    const map = new Map<string, string>();
    for (const level of levels.data ?? []) map.set(level.product_id, level.quantity_on_hand);
    return map;
  }, [levels.data]);

  const lowIds = useMemo(
    () => new Set((lowStock.data ?? []).map((item) => item.product_id)),
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
          subtext="On-hand × average cost"
        />
        <KpiCard title="Products" value={String(products.data?.length ?? "—")} />
        <KpiCard
          title="Low stock"
          value={String(lowStock.data?.length ?? "—")}
          urgentBadge={lowStock.data && lowStock.data.length > 0 ? { label: "Reorder" } : undefined}
        />
      </div>

      <div className="grid gap-6 lg:grid-cols-[1.1fr_0.9fr]">
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
              {products.data?.map((product) => {
                const isLow = lowIds.has(product.id);
                const onHand = onHandById.get(product.id) ?? "0";
                return (
                  <li key={product.id}>
                    <button
                      type="button"
                      onClick={() => setSelectedProductId(product.id)}
                      className={`w-full rounded-lg border px-3 py-3 text-left transition-colors ${
                        selectedProductId === product.id
                          ? "border-lf-primary bg-lf-primary/10"
                          : "border-lf-outline-variant/20 bg-lf-surface hover:border-lf-primary/50"
                      }`}
                    >
                      <div className="flex items-center justify-between gap-3">
                        <div>
                          <p className="text-sm font-semibold text-lf-on-surface">{product.name}</p>
                          <p className="text-xs text-lf-on-surface-variant">SKU {product.sku}</p>
                        </div>
                        <span
                          className={`rounded-full px-2 py-1 text-[10px] font-semibold uppercase tracking-widest ${
                            isLow
                              ? "bg-lf-error-container text-lf-on-error-container"
                              : "bg-lf-secondary-container text-lf-on-secondary-container"
                          }`}
                        >
                          {isLow ? "Low stock" : "Active"}
                        </span>
                      </div>
                      <div className="mt-2 flex flex-wrap items-center gap-3 text-xs text-lf-on-surface-variant">
                        <span>On hand: {onHand}</span>
                        <span>Reorder: {product.reorder_level}</span>
                        <span>Unit: {product.unit}</span>
                      </div>
                    </button>
                  </li>
                );
              })}
            </ul>
          </QueryState>
        </div>

        <div>
          {selectedProductId ? (
            <ProductDetailPanel productId={selectedProductId} />
          ) : (
            <div className="rounded-xl border border-lf-outline-variant/10 bg-lf-surface-container-lowest p-6 text-sm text-lf-on-surface-variant">
              Select a product to view its stock level and movement history.
            </div>
          )}
        </div>
      </div>

      {showNew && (
        <Modal title="Create product" onClose={() => setShowNew(false)}>
          <NewProductForm onDone={() => setShowNew(false)} />
        </Modal>
      )}
    </div>
  );
}
