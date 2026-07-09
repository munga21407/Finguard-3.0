"use client";

import { useEffect, useMemo, useState, type FormEvent } from "react";
import {
  ArrowDownToLine,
  ArrowUpFromLine,
  ClipboardList,
  Package,
  Plus,
  RotateCcw,
  Search,
  SlidersHorizontal,
} from "lucide-react";
import { QueryState } from "@/components/ui/QueryState";
import {
  useApplyStockMovement,
  useCreateInventoryProduct,
  useInventoryProducts,
  useInventorySummary,
  useInventoryValuation,
  useProductMovements,
  useStockLevels,
} from "@/lib/hooks/useInventoryData";
import { cn } from "@/lib/utils/cn";
import { formatDateTime, formatMoney } from "@/lib/utils/format";
import type {
  ApiInventoryProduct,
  ApiStockLevel,
  ApiStockMovementReason,
  ApiStockMovementType,
  ApiUnitOfMeasure,
} from "@/types/api";

const UNITS: ApiUnitOfMeasure[] = ["each", "kg", "litre", "metre", "box", "pack"];
const EMPTY_PRODUCTS: ApiInventoryProduct[] = [];
const EMPTY_LEVELS: ApiStockLevel[] = [];
const MOVEMENTS: Array<{
  value: ApiStockMovementType;
  label: string;
  icon: typeof ArrowDownToLine;
}> = [
  { value: "receipt", label: "Receive", icon: ArrowDownToLine },
  { value: "issue", label: "Issue", icon: ArrowUpFromLine },
  { value: "sale", label: "Sale", icon: Package },
  { value: "return_in", label: "Return", icon: RotateCcw },
  { value: "adjustment", label: "Adjust", icon: SlidersHorizontal },
];
const REASONS: ApiStockMovementReason[] = [
  "purchase",
  "sale",
  "damage",
  "theft",
  "stock_take",
  "expiry",
  "correction",
  "other",
];

const num = (value: string | number | null | undefined): number =>
  value == null ? 0 : typeof value === "string" ? Number(value) || 0 : value;

function formatQuantity(value: string | number | null | undefined, unit?: string): string {
  const n = num(value);
  const formatted = n.toLocaleString("en-KE", {
    minimumFractionDigits: n % 1 === 0 ? 0 : 3,
    maximumFractionDigits: 3,
  });
  return unit ? `${formatted} ${unit}` : formatted;
}

function levelFor(product: ApiInventoryProduct, levels: ApiStockLevel[]): ApiStockLevel | null {
  return product.stock_level ?? levels.find((level) => level.product_id === product.id) ?? null;
}

function lowStock(product: ApiInventoryProduct, level: ApiStockLevel | null): boolean {
  return num(level?.quantity_on_hand) <= num(product.reorder_level);
}

function KpiCard({
  label,
  value,
  icon: Icon,
}: {
  label: string;
  value: string;
  icon: typeof Package;
}) {
  return (
    <div className="bg-lf-surface-container-lowest rounded-xl border border-lf-outline-variant/10 p-5 shadow-[0_4px_20px_rgba(0,0,0,0.03)]">
      <div className="flex items-center justify-between gap-3">
        <span className="text-xs font-semibold tracking-widest uppercase text-lf-on-surface-variant">
          {label}
        </span>
        <Icon size={18} className="text-lf-primary" />
      </div>
      <p className="mt-3 text-2xl font-bold tracking-tight text-lf-on-surface">{value}</p>
    </div>
  );
}

function ProductCreateForm() {
  const create = useCreateInventoryProduct();
  const [open, setOpen] = useState(false);
  const [sku, setSku] = useState("");
  const [name, setName] = useState("");
  const [unit, setUnit] = useState<ApiUnitOfMeasure>("each");
  const [category, setCategory] = useState("");
  const [costPrice, setCostPrice] = useState("");
  const [sellingPrice, setSellingPrice] = useState("");
  const [reorderLevel, setReorderLevel] = useState("0");
  const [reorderQuantity, setReorderQuantity] = useState("0");
  const [barcode, setBarcode] = useState("");

  const canSubmit =
    sku.trim() !== "" &&
    name.trim() !== "" &&
    Number(costPrice) >= 0 &&
    Number(sellingPrice) >= 0 &&
    !create.isPending;

  function submit(event: FormEvent) {
    event.preventDefault();
    if (!canSubmit) return;
    create.mutate(
      {
        sku: sku.trim(),
        name: name.trim(),
        unit,
        category: category.trim() || null,
        cost_price: costPrice || "0",
        selling_price: sellingPrice || "0",
        reorder_level: reorderLevel || "0",
        reorder_quantity: reorderQuantity || "0",
        barcode: barcode.trim() || null,
      },
      {
        onSuccess: () => {
          setSku("");
          setName("");
          setCategory("");
          setCostPrice("");
          setSellingPrice("");
          setReorderLevel("0");
          setReorderQuantity("0");
          setBarcode("");
          setOpen(false);
        },
      },
    );
  }

  return (
    <div className="bg-lf-surface-container-lowest rounded-xl border border-lf-outline-variant/10 p-5 shadow-[0_4px_20px_rgba(0,0,0,0.03)]">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        className="flex w-full items-center justify-between gap-3 text-left"
      >
        <span>
          <span className="block text-base font-bold text-lf-on-surface">Product catalog</span>
          <span className="block text-xs text-lf-on-surface-variant">
            Add SKUs, prices, units, and reorder policy.
          </span>
        </span>
        <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-lf-primary text-lf-on-primary">
          <Plus size={17} />
        </span>
      </button>

      {open && (
        <form onSubmit={submit} className="mt-5 grid grid-cols-1 gap-3 md:grid-cols-2">
          <input
            value={sku}
            onChange={(event) => setSku(event.target.value)}
            placeholder="SKU"
            className="rounded-lg border border-lf-outline-variant/40 bg-lf-surface px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-lf-primary/30"
          />
          <input
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="Product name"
            className="rounded-lg border border-lf-outline-variant/40 bg-lf-surface px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-lf-primary/30"
          />
          <select
            value={unit}
            onChange={(event) => setUnit(event.target.value as ApiUnitOfMeasure)}
            className="rounded-lg border border-lf-outline-variant/40 bg-lf-surface px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-lf-primary/30"
          >
            {UNITS.map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
          <input
            value={category}
            onChange={(event) => setCategory(event.target.value)}
            placeholder="Category"
            className="rounded-lg border border-lf-outline-variant/40 bg-lf-surface px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-lf-primary/30"
          />
          <input
            value={costPrice}
            onChange={(event) => setCostPrice(event.target.value)}
            inputMode="decimal"
            placeholder="Cost price"
            className="rounded-lg border border-lf-outline-variant/40 bg-lf-surface px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-lf-primary/30"
          />
          <input
            value={sellingPrice}
            onChange={(event) => setSellingPrice(event.target.value)}
            inputMode="decimal"
            placeholder="Selling price"
            className="rounded-lg border border-lf-outline-variant/40 bg-lf-surface px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-lf-primary/30"
          />
          <input
            value={reorderLevel}
            onChange={(event) => setReorderLevel(event.target.value)}
            inputMode="decimal"
            placeholder="Reorder level"
            className="rounded-lg border border-lf-outline-variant/40 bg-lf-surface px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-lf-primary/30"
          />
          <input
            value={reorderQuantity}
            onChange={(event) => setReorderQuantity(event.target.value)}
            inputMode="decimal"
            placeholder="Reorder quantity"
            className="rounded-lg border border-lf-outline-variant/40 bg-lf-surface px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-lf-primary/30"
          />
          <input
            value={barcode}
            onChange={(event) => setBarcode(event.target.value)}
            placeholder="Barcode"
            className="rounded-lg border border-lf-outline-variant/40 bg-lf-surface px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-lf-primary/30 md:col-span-2"
          />
          <div className="flex items-center gap-3 md:col-span-2">
            <button
              type="submit"
              disabled={!canSubmit}
              className="rounded-lg bg-lf-primary px-4 py-2.5 text-xs font-bold text-lf-on-primary transition-opacity hover:opacity-90 disabled:opacity-50"
            >
              {create.isPending ? "Creating..." : "Create product"}
            </button>
            {create.isError && (
              <span className="text-xs text-lf-error">
                Could not create product. Check SKU uniqueness and permissions.
              </span>
            )}
          </div>
        </form>
      )}
    </div>
  );
}

function MovementForm({ product }: { product: ApiInventoryProduct }) {
  const apply = useApplyStockMovement();
  const [movementType, setMovementType] = useState<ApiStockMovementType>("receipt");
  const [quantity, setQuantity] = useState("");
  const [unitCost, setUnitCost] = useState("");
  const [reason, setReason] = useState<ApiStockMovementReason>("purchase");
  const [referenceType, setReferenceType] = useState("");
  const [referenceId, setReferenceId] = useState("");
  const [note, setNote] = useState("");

  const needsReason = movementType === "adjustment";
  const canSubmit =
    Number(quantity) > 0 &&
    (!needsReason || reason !== null) &&
    !(movementType === "receipt" && unitCost.trim() === "") &&
    !apply.isPending;

  function submit(event: FormEvent) {
    event.preventDefault();
    if (!canSubmit) return;
    apply.mutate(
      {
        productId: product.id,
        body: {
          product_id: product.id,
          movement_type: movementType,
          quantity,
          unit_cost: unitCost.trim() || null,
          reason: needsReason ? reason : null,
          reference_type: referenceType.trim() || null,
          reference_id: referenceId.trim() || null,
          note: note.trim() || null,
        },
      },
      {
        onSuccess: () => {
          setQuantity("");
          setUnitCost("");
          setReferenceType("");
          setReferenceId("");
          setNote("");
        },
      },
    );
  }

  return (
    <form onSubmit={submit} className="rounded-xl border border-lf-outline-variant/10 bg-lf-surface-container-lowest p-5">
      <div className="mb-4 flex items-center justify-between gap-3">
        <div>
          <h3 className="text-base font-bold text-lf-on-surface">Record movement</h3>
          <p className="text-xs text-lf-on-surface-variant">
            Every stock change is posted to the append-only ledger.
          </p>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-2">
        {MOVEMENTS.map(({ value, label, icon: Icon }) => (
          <button
            key={value}
            type="button"
            onClick={() => setMovementType(value)}
            className={cn(
              "flex items-center justify-center gap-2 rounded-lg border px-3 py-2 text-xs font-semibold transition-colors",
              movementType === value
                ? "border-lf-primary bg-lf-primary text-lf-on-primary"
                : "border-lf-outline-variant/30 text-lf-on-surface-variant hover:bg-lf-surface-container",
            )}
          >
            <Icon size={14} />
            {label}
          </button>
        ))}
      </div>

      <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2">
        <input
          value={quantity}
          onChange={(event) => setQuantity(event.target.value)}
          inputMode="decimal"
          placeholder={`Quantity (${product.unit})`}
          className="rounded-lg border border-lf-outline-variant/40 bg-lf-surface px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-lf-primary/30"
        />
        <input
          value={unitCost}
          onChange={(event) => setUnitCost(event.target.value)}
          inputMode="decimal"
          placeholder={movementType === "receipt" ? "Unit cost required" : "Unit cost optional"}
          className="rounded-lg border border-lf-outline-variant/40 bg-lf-surface px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-lf-primary/30"
        />
        {needsReason && (
          <select
            value={reason}
            onChange={(event) => setReason(event.target.value as ApiStockMovementReason)}
            className="rounded-lg border border-lf-outline-variant/40 bg-lf-surface px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-lf-primary/30 sm:col-span-2"
          >
            {REASONS.map((option) => (
              <option key={option} value={option}>
                {option.replace("_", " ")}
              </option>
            ))}
          </select>
        )}
        <input
          value={referenceType}
          onChange={(event) => setReferenceType(event.target.value)}
          placeholder="Reference type"
          className="rounded-lg border border-lf-outline-variant/40 bg-lf-surface px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-lf-primary/30"
        />
        <input
          value={referenceId}
          onChange={(event) => setReferenceId(event.target.value)}
          placeholder="Reference id"
          className="rounded-lg border border-lf-outline-variant/40 bg-lf-surface px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-lf-primary/30"
        />
        <input
          value={note}
          onChange={(event) => setNote(event.target.value)}
          placeholder="Note"
          className="rounded-lg border border-lf-outline-variant/40 bg-lf-surface px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-lf-primary/30 sm:col-span-2"
        />
      </div>

      <div className="mt-4 flex items-center gap-3">
        <button
          type="submit"
          disabled={!canSubmit}
          className="rounded-lg bg-lf-primary px-4 py-2.5 text-xs font-bold text-lf-on-primary transition-opacity hover:opacity-90 disabled:opacity-50"
        >
          {apply.isPending ? "Posting..." : "Post movement"}
        </button>
        {apply.isError && (
          <span className="text-xs text-lf-error">
            Movement rejected. Check stock on hand, required fields, and permissions.
          </span>
        )}
      </div>
    </form>
  );
}

function ProductList({
  products,
  levels,
  selectedId,
  onSelect,
}: {
  products: ApiInventoryProduct[];
  levels: ApiStockLevel[];
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
  levels: ApiStockLevel[];
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

          {valuationQ.data && valuationQ.data.by_category.length > 0 && (
            <div className="rounded-xl border border-lf-outline-variant/10 bg-lf-surface-container-lowest p-5 shadow-[0_4px_20px_rgba(0,0,0,0.03)]">
              <h3 className="mb-4 text-base font-bold text-lf-on-surface">
                Valuation by category
              </h3>
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {valuationQ.data.by_category.map((category) => (
                  <div
                    key={category.category ?? "uncategorized"}
                    className="rounded-lg border border-lf-outline-variant/10 bg-lf-surface p-4"
                  >
                    <p className="text-xs font-semibold uppercase tracking-widest text-lf-on-surface-variant">
                      {category.category ?? "Uncategorized"}
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
