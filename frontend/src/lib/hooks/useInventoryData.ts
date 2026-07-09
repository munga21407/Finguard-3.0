"use client";

// TanStack Query hooks for the Stock Management module.

import { useMemo } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  adjustStock,
  applyStockMovement,
  createInventoryProduct,
  getInventoryProduct,
  getInventoryValuation,
  listInventoryProducts,
  listLowStockItems,
  listProductMovements,
  listStockLevels,
  updateInventoryProduct,
} from "@/lib/api/inventory";
import type {
  ApiInventoryProduct,
  ApiInventoryProductCreate,
  ApiInventoryProductListParams,
  ApiInventoryProductUpdate,
  ApiLowStockItem,
  ApiStockLevel,
  ApiStockMovement,
  ApiStockMovementCreate,
  ApiValuationReport,
} from "@/types/api";

export const inventoryKeys = {
  products: (params?: ApiInventoryProductListParams) =>
    ["inventory", "products", params ?? {}] as const,
  product: (id: string) => ["inventory", "products", id] as const,
  levels: ["inventory", "levels"] as const,
  movements: (productId: string) => ["inventory", "products", productId, "movements"] as const,
  valuation: ["inventory", "reports", "valuation"] as const,
  lowStock: ["inventory", "reports", "low-stock"] as const,
};

function invalidateInventory(queryClient: ReturnType<typeof useQueryClient>) {
  queryClient.invalidateQueries({ queryKey: ["inventory"] });
}

export function useInventoryProducts(params?: ApiInventoryProductListParams) {
  return useQuery<ApiInventoryProduct[]>({
    queryKey: inventoryKeys.products(params),
    queryFn: () => listInventoryProducts(params),
  });
}

export function useInventoryProduct(id: string | null) {
  return useQuery<ApiInventoryProduct>({
    queryKey: inventoryKeys.product(id ?? "none"),
    queryFn: () => getInventoryProduct(id as string),
    enabled: id !== null,
  });
}

export function useStockLevels() {
  return useQuery<ApiStockLevel[]>({
    queryKey: inventoryKeys.levels,
    queryFn: listStockLevels,
  });
}

export function useProductMovements(productId: string | null) {
  return useQuery<ApiStockMovement[]>({
    queryKey: inventoryKeys.movements(productId ?? "none"),
    queryFn: () => listProductMovements(productId as string),
    enabled: productId !== null,
  });
}

export function useInventoryValuation() {
  return useQuery<ApiValuationReport>({
    queryKey: inventoryKeys.valuation,
    queryFn: getInventoryValuation,
  });
}

export function useLowStockItems() {
  return useQuery<ApiLowStockItem[]>({
    queryKey: inventoryKeys.lowStock,
    queryFn: listLowStockItems,
  });
}

export function useCreateInventoryProduct() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: ApiInventoryProductCreate) => createInventoryProduct(body),
    onSuccess: () => invalidateInventory(queryClient),
  });
}

export function useUpdateInventoryProduct() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: ApiInventoryProductUpdate }) =>
      updateInventoryProduct(id, body),
    onSuccess: (_, vars) => {
      invalidateInventory(queryClient);
      queryClient.invalidateQueries({ queryKey: inventoryKeys.product(vars.id) });
    },
  });
}

export function useApplyStockMovement() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ productId, body }: { productId: string; body: ApiStockMovementCreate }) =>
      body.movement_type === "adjustment"
        ? adjustStock(productId, body)
        : applyStockMovement(productId, body),
    onSuccess: (_, vars) => {
      invalidateInventory(queryClient);
      queryClient.invalidateQueries({ queryKey: inventoryKeys.product(vars.productId) });
      queryClient.invalidateQueries({ queryKey: inventoryKeys.movements(vars.productId) });
    },
  });
}

export interface InventorySummary {
  productCount: number;
  activeCount: number;
  lowStockCount: number;
  totalValue: number | null;
}

const num = (value: string | number | null | undefined): number =>
  value == null ? 0 : typeof value === "string" ? Number(value) || 0 : value;

export function useInventorySummary(params?: ApiInventoryProductListParams): {
  data: InventorySummary;
  isLoading: boolean;
  isError: boolean;
} {
  const productsQ = useInventoryProducts(params);
  const lowStockQ = useLowStockItems();
  const valuationQ = useInventoryValuation();

  const data = useMemo<InventorySummary>(() => {
    const products = productsQ.data ?? [];
    return {
      productCount: products.length,
      activeCount: products.filter((product) => product.is_active).length,
      lowStockCount: lowStockQ.data?.length ?? 0,
      totalValue: valuationQ.data ? num(valuationQ.data.total_value) : null,
    };
  }, [lowStockQ.data, productsQ.data, valuationQ.data]);

  return {
    data,
    isLoading: productsQ.isLoading || lowStockQ.isLoading || valuationQ.isLoading,
    isError: productsQ.isError || lowStockQ.isError || valuationQ.isError,
  };
}
