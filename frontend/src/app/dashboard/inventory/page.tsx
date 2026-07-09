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

function ProductList({
  products,
  levels,
  selectedId,
  onSelect,
}: {
  products: ApiInventoryProduct[];
  levels: ApiStockLevelView[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  return (
    <div className="overflow-hidden rounded-xl border border-lf-outline-variant/10 bg-lf-surface-container-lowest shadow-[0_4px_20px_rgba(0,0,0,0.03)]">
      <div className="grid grid-cols-[1.3fr_0.7fr_0.7fr_0.7fr] gap-3 border-b border-lf-outline-variant/10 px-4 py-3 text-[11px] font-bold uppercase tracking-widest text-lf-on-surface-variant">
        <span>Product</span>
        <span>On hand</span>
        <span>Reorder</span>
        <span>Status</span>
      </div>
      <div className="divide-y divide-lf-outline-variant/10">
        {products.map((product) => {
          const level = levelFor(product, levels);
          const isLow = lowStock(product, level);
          return (
            <button
              key={product.id}
              type="button"
              onClick={() => onSelect(product.id)}
              className={cn(
                "grid w-full grid-cols-[1.3fr_0.7fr_0.7fr_0.7fr] gap-3 px-4 py-3 text-left transition-colors hover:bg-lf-surface-container",
                selectedId === product.id && "bg-lf-primary-fixed/20",
              )}
            >
              <span className="min-w-0">
                <span className="block truncate text-sm font-semibold text-lf-on-surface">
                  {product.name}
                </span>
                <span className="block truncate text-xs text-lf-on-surface-variant">
                  {product.sku} {product.category ? `- ${product.category}` : ""}
                </span>
              </span>
              <span className="text-sm font-semibold text-lf-on-surface">
                {formatQuantity(level?.quantity_on_hand, product.unit)}
              </span>
              <span className="text-sm text-lf-on-surface-variant">
                {formatQuantity(product.reorder_level, product.unit)}
              </span>
              <span>
                <span
                  className={cn(
                    "inline-flex rounded-full px-2 py-0.5 text-[10px] font-bold uppercase",
                    isLow
                      ? "bg-lf-error-container text-lf-on-error-container"
                      : "bg-[#dcfce7] text-[#166534]",
                  )}
                >
                  {isLow ? "Low" : "OK"}
                </span>
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}

function ProductDetail({
  product,
  levels,
}: {
  product: ApiInventoryProduct | null;
  levels: ApiStockLevelView[];
}) {
  const movementsQ = useProductMovements(product?.id ?? null);
  const level = product ? levelFor(product, levels) : null;

  if (!product) {
    return (
      <div className="rounded-xl border border-dashed border-lf-outline-variant/40 p-8 text-center text-sm text-lf-on-surface-variant">
        Select a product to inspect its ledger.
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-5">
      <div className="rounded-xl border border-lf-outline-variant/10 bg-lf-surface-container-lowest p-5 shadow-[0_4px_20px_rgba(0,0,0,0.03)]">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h3 className="text-xl font-bold tracking-tight text-lf-on-surface">
              {product.name}
            </h3>
            <p className="text-xs font-semibold uppercase tracking-widest text-lf-on-surface-variant">
              {product.sku}
            </p>
          </div>
          <span
            className={cn(
              "rounded-full px-2 py-0.5 text-[10px] font-bold uppercase",
              product.is_active
                ? "bg-[#dcfce7] text-[#166534]"
                : "bg-lf-surface-container text-lf-on-surface-variant",
            )}
          >
            {product.is_active ? "Active" : "Inactive"}
          </span>
        </div>
        <div className="mt-5 grid grid-cols-2 gap-3">
          <div>
            <span className="text-[11px] font-bold uppercase tracking-widest text-lf-on-surface-variant">
              On hand
            </span>
            <p className="mt-1 text-lg font-bold text-lf-on-surface">
              {formatQuantity(level?.quantity_on_hand, product.unit)}
            </p>
          </div>
          <div>
            <span className="text-[11px] font-bold uppercase tracking-widest text-lf-on-surface-variant">
              Average cost
            </span>
            <p className="mt-1 text-lg font-bold text-lf-on-surface">
              {formatMoney(level?.average_cost ?? "0")}
            </p>
          </div>
          <div>
            <span className="text-[11px] font-bold uppercase tracking-widest text-lf-on-surface-variant">
              Reorder
            </span>
            <p className="mt-1 text-sm font-semibold text-lf-on-surface">
              {formatQuantity(product.reorder_level, product.unit)}
            </p>
          </div>
          <div>
            <span className="text-[11px] font-bold uppercase tracking-widest text-lf-on-surface-variant">
              Selling price
            </span>
            <p className="mt-1 text-sm font-semibold text-lf-on-surface">
              {formatMoney(product.selling_price)}
            </p>
          </div>
        </div>
      </div>

      <MovementForm product={product} />

      <div className="rounded-xl border border-lf-outline-variant/10 bg-lf-surface-container-lowest p-5 shadow-[0_4px_20px_rgba(0,0,0,0.03)]">
        <div className="mb-4 flex items-center gap-2">
          <ClipboardList size={17} className="text-lf-primary" />
          <h3 className="text-base font-bold text-lf-on-surface">Movement history</h3>
        </div>
        <QueryState
          isLoading={movementsQ.isLoading}
          isError={movementsQ.isError}
          isEmpty={(movementsQ.data ?? []).length === 0}
          onRetry={() => movementsQ.refetch()}
          loadingLabel="Loading movements..."
          errorLabel="Couldn't load the stock ledger."
          emptyLabel="No movements posted for this product yet."
        >
          <div className="flex flex-col divide-y divide-lf-outline-variant/10">
            {(movementsQ.data ?? []).map((movement) => (
              <div key={movement.id} className="flex items-center justify-between gap-3 py-3">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-sm font-semibold capitalize text-lf-on-surface">
                      {movement.movement_type.replace("_", " ")}
                    </span>
                    <span className="rounded-full bg-lf-surface-container px-2 py-0.5 text-[10px] font-bold text-lf-on-surface-variant">
                      #{movement.sequence}
                    </span>
                  </div>
                  <p className="mt-0.5 truncate text-xs text-lf-on-surface-variant">
                    {movement.note || movement.reference_type || "Ledger movement"} -{" "}
                    {formatDateTime(movement.created_at)}
                  </p>
                </div>
                <div className="shrink-0 text-right">
                  <p className="text-sm font-bold text-lf-on-surface">
                    {formatQuantity(movement.quantity, product.unit)}
                  </p>
                  <p className="text-xs text-lf-on-surface-variant">
                    balance {formatQuantity(movement.balance_after, product.unit)}
                  </p>
                </div>
              </div>
            ))}
          </div>
        </QueryState>
      </div>
    </div>
  );
}

export default function InventoryPage() {
  const [query, setQuery] = useState("");
  const [lowOnly, setLowOnly] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const params = useMemo(
    () => ({
      q: query.trim() || undefined,
      low_stock: lowOnly || undefined,
      limit: 100,
      offset: 0,
    }),
    [lowOnly, query],
  );
  const productsQ = useInventoryProducts(params);
  const levelsQ = useStockLevels();
  const valuationQ = useInventoryValuation();
  const summary = useInventorySummary(params);

  const products = productsQ.data ?? EMPTY_PRODUCTS;
  const levels = levelsQ.data ?? EMPTY_LEVELS;
  const selectedProduct = products.find((product) => product.id === selectedId) ?? null;

  useEffect(() => {
    if (selectedId === null && products.length > 0) {
      setSelectedId(products[0].id);
    }
    if (selectedId !== null && products.length > 0 && !products.some((p) => p.id === selectedId)) {
      setSelectedId(products[0].id);
    }
  }, [products, selectedId]);

  return (
    <div className="mx-auto flex max-w-7xl flex-col gap-6">
      <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-end">
        <div>
          <h2 className="text-2xl font-bold tracking-tight text-lf-on-background md:text-3xl">
            Stock Management
          </h2>
          <p className="mt-1 text-base text-lf-on-surface-variant">
            Track products, on-hand quantity, valuation, and immutable stock movements.
          </p>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-5 xl:grid-cols-4">
        <KpiCard label="Products" value={String(summary.data.productCount)} icon={Package} />
        <KpiCard label="Active SKUs" value={String(summary.data.activeCount)} icon={ClipboardList} />
        <KpiCard label="Low Stock" value={String(summary.data.lowStockCount)} icon={ArrowUpFromLine} />
        <KpiCard
          label="Inventory Value"
          value={summary.data.totalValue === null ? "..." : formatMoney(summary.data.totalValue)}
          icon={ArrowDownToLine}
        />
      </div>

      {summary.isError && (
        <div className="rounded-lg border border-lf-error-container bg-lf-error-container/30 px-4 py-3 text-sm text-lf-error">
          Some inventory summary data could not be loaded.
        </div>
      )}

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-[minmax(0,1.35fr)_minmax(360px,0.65fr)]">
        <div className="flex flex-col gap-5">
          <div className="rounded-xl border border-lf-outline-variant/10 bg-lf-surface-container-lowest p-4 shadow-[0_4px_20px_rgba(0,0,0,0.03)]">
            <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
              <div className="relative flex-1">
                <Search
                  size={16}
                  className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-lf-on-surface-variant"
                />
                <input
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  placeholder="Search SKU, product, category..."
                  className="w-full rounded-lg border border-lf-outline-variant/40 bg-lf-surface py-2 pl-9 pr-3 text-sm focus:outline-none focus:ring-2 focus:ring-lf-primary/30"
                />
              </div>
              <label className="flex items-center gap-2 rounded-lg border border-lf-outline-variant/30 px-3 py-2 text-xs font-semibold text-lf-on-surface-variant">
                <input
                  type="checkbox"
                  checked={lowOnly}
                  onChange={(event) => setLowOnly(event.target.checked)}
                  className="h-4 w-4 accent-lf-primary"
                />
                Low stock only
              </label>
            </div>
          </div>

          <ProductCreateForm />

          <QueryState
            isLoading={productsQ.isLoading || levelsQ.isLoading}
            isError={productsQ.isError || levelsQ.isError}
            isEmpty={products.length === 0}
            onRetry={() => {
              productsQ.refetch();
              levelsQ.refetch();
              valuationQ.refetch();
            }}
            loadingLabel="Loading inventory..."
            errorLabel="Couldn't load inventory products."
            emptyLabel="No stock products yet. Add the first SKU above."
          >
            <ProductList
              products={products}
              levels={levels}
              selectedId={selectedId}
              onSelect={setSelectedId}
            />
          </QueryState>

          {valuationQ.data && valuationQ.data.categories.length > 0 && (
            <div className="rounded-xl border border-lf-outline-variant/10 bg-lf-surface-container-lowest p-5 shadow-[0_4px_20px_rgba(0,0,0,0.03)]">
              <h3 className="mb-4 text-base font-bold text-lf-on-surface">
                Valuation by category
              </h3>
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {valuationQ.data.categories.map((category) => (
                  <div
                    key={category.category}
                    className="rounded-lg border border-lf-outline-variant/10 bg-lf-surface p-4"
                  >
                    <p className="text-xs font-semibold uppercase tracking-widest text-lf-on-surface-variant">
                      {category.category || "Uncategorized"}
                    </p>
                    <p className="mt-2 text-lg font-bold text-lf-on-surface">
                      {formatMoney(category.value)}
                    </p>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        <ProductDetail product={selectedProduct} levels={levels} />
      </div>
    </div>
  );
}
