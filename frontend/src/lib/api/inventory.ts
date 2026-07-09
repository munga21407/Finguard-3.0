// Inventory API
// Frontend contract for the Stock Management module described in
// STOCK_MANAGEMENT_MODULE.pdf. These wrappers are ready for the backend
// /api/v1/inventory domain and use the shared cookie-authenticated httpClient.

import httpClient from "@/lib/api/http-client";
import { ENDPOINTS } from "@/lib/api/endpoints";
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

export async function listInventoryProducts(
  params?: ApiInventoryProductListParams,
): Promise<ApiInventoryProduct[]> {
  const { data } = await httpClient.get<ApiInventoryProduct[]>(
    ENDPOINTS.INVENTORY.PRODUCTS,
    { params },
  );
  return data;
}

export async function getInventoryProduct(id: string): Promise<ApiInventoryProduct> {
  const { data } = await httpClient.get<ApiInventoryProduct>(
    ENDPOINTS.INVENTORY.PRODUCT(id),
  );
  return data;
}

export async function createInventoryProduct(
  body: ApiInventoryProductCreate,
): Promise<ApiInventoryProduct> {
  const { data } = await httpClient.post<ApiInventoryProduct>(
    ENDPOINTS.INVENTORY.PRODUCTS,
    body,
  );
  return data;
}

export async function updateInventoryProduct(
  id: string,
  body: ApiInventoryProductUpdate,
): Promise<ApiInventoryProduct> {
  const { data } = await httpClient.patch<ApiInventoryProduct>(
    ENDPOINTS.INVENTORY.PRODUCT(id),
    body,
  );
  return data;
}

export async function listStockLevels(): Promise<ApiStockLevel[]> {
  const { data } = await httpClient.get<ApiStockLevel[]>(ENDPOINTS.INVENTORY.LEVELS);
  return data;
}

export async function listProductMovements(
  productId: string,
): Promise<ApiStockMovement[]> {
  const { data } = await httpClient.get<ApiStockMovement[]>(
    ENDPOINTS.INVENTORY.PRODUCT_MOVEMENTS(productId),
  );
  return data;
}

export async function applyStockMovement(
  productId: string,
  body: ApiStockMovementCreate,
): Promise<ApiStockMovement> {
  const { data } = await httpClient.post<ApiStockMovement>(
    ENDPOINTS.INVENTORY.PRODUCT_MOVEMENTS(productId),
    body,
  );
  return data;
}

export async function adjustStock(
  productId: string,
  body: ApiStockMovementCreate,
): Promise<ApiStockMovement> {
  const { data } = await httpClient.post<ApiStockMovement>(
    ENDPOINTS.INVENTORY.PRODUCT_ADJUST(productId),
    body,
  );
  return data;
}

export async function getInventoryValuation(): Promise<ApiValuationReport> {
  const { data } = await httpClient.get<ApiValuationReport>(
    ENDPOINTS.INVENTORY.VALUATION_REPORT,
  );
  return data;
}

export async function listLowStockItems(): Promise<ApiLowStockItem[]> {
  const { data } = await httpClient.get<ApiLowStockItem[]>(
    ENDPOINTS.INVENTORY.LOW_STOCK_REPORT,
  );
  return data;
}
