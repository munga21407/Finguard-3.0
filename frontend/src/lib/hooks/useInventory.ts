// ─── Inventory data hooks ───────────────────────────────────────────────────────
// TanStack Query hooks over the inventory endpoints. The product/detail queries
// feed the Stock Management UI; the movement/adjust mutations invalidate the
// affected product, its stock level, its history, and the cross-product reports
// so on-hand + low-stock badges stay live.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  adjustStock,
  createProduct,
  getProduct,
  getStockLevel,
  getValuation,
  listLevels,
  listLowStock,
  listMovements,
  listProducts,
  recordMovement,
} from "@/lib/api/inventory";
import type {
  ApiMovementCreate,
  ApiProductCreate,
  ApiStockAdjustmentCreate,
} from "@/types/api";

export const inventoryKeys = {
  products: ["inventory", "products"] as const,
  product: (id: string) => ["inventory", "product", id] as const,
  stock: (id: string) => ["inventory", "stock", id] as const,
  movements: (id: string) => ["inventory", "movements", id] as const,
  levels: ["inventory", "levels"] as const,
  valuation: ["inventory", "valuation"] as const,
  lowStock: ["inventory", "low-stock"] as const,
};

export function useProducts() {
  return useQuery({ queryKey: inventoryKeys.products, queryFn: () => listProducts() });
}

export function useProduct(id: string) {
  return useQuery({
    queryKey: inventoryKeys.product(id),
    queryFn: () => getProduct(id),
    enabled: Boolean(id),
  });
}

export function useStockLevel(id: string) {
  return useQuery({
    queryKey: inventoryKeys.stock(id),
    queryFn: () => getStockLevel(id),
    enabled: Boolean(id),
  });
}

export function useMovements(id: string) {
  return useQuery({
    queryKey: inventoryKeys.movements(id),
    queryFn: () => listMovements(id),
    enabled: Boolean(id),
  });
}

export function useLevels() {
  return useQuery({ queryKey: inventoryKeys.levels, queryFn: listLevels });
}

export function useValuation() {
  return useQuery({ queryKey: inventoryKeys.valuation, queryFn: getValuation });
}

export function useLowStock() {
  return useQuery({ queryKey: inventoryKeys.lowStock, queryFn: listLowStock });
}

function useInvalidateProduct() {
  const qc = useQueryClient();
  return (id: string) => {
    void qc.invalidateQueries({ queryKey: inventoryKeys.product(id) });
    void qc.invalidateQueries({ queryKey: inventoryKeys.stock(id) });
    void qc.invalidateQueries({ queryKey: inventoryKeys.movements(id) });
    void qc.invalidateQueries({ queryKey: inventoryKeys.products });
    void qc.invalidateQueries({ queryKey: inventoryKeys.levels });
    void qc.invalidateQueries({ queryKey: inventoryKeys.valuation });
    void qc.invalidateQueries({ queryKey: inventoryKeys.lowStock });
  };
}

export function useCreateProduct() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: ApiProductCreate) => createProduct(payload),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: inventoryKeys.products });
      void qc.invalidateQueries({ queryKey: inventoryKeys.levels });
    },
  });
}

export function useRecordMovement(productId: string) {
  const invalidate = useInvalidateProduct();
  return useMutation({
    mutationFn: (payload: ApiMovementCreate) => recordMovement(productId, payload),
    onSuccess: () => invalidate(productId),
  });
}

export function useAdjustStock(productId: string) {
  const invalidate = useInvalidateProduct();
  return useMutation({
    mutationFn: (payload: ApiStockAdjustmentCreate) => adjustStock(productId, payload),
    onSuccess: () => invalidate(productId),
  });
}
