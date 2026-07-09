// Inventory API
// Frontend contract for the Stock Management module. The wrappers below support
// both the newer inventory UI and the existing inventory hooks through a shared
// endpoint layer.

import { ENDPOINTS } from "@/lib/api/endpoints";
import httpClient from "@/lib/api/http-client";
import type {
  ApiInventoryProduct,
  ApiInventoryProductCreate,
  ApiInventoryProductListParams,
  ApiInventoryProductUpdate,
  ApiLowStockItem,
  ApiMovementCreate,
  ApiProduct,
  ApiProductCreate,
  ApiStockAdjustmentCreate,
  ApiStockLevel,
  ApiStockLevelView,
  ApiStockMovement,
  ApiStockMovementCreate,
  ApiValuationReport,
} from "@/types/api";

export async function listInventoryProducts(
  params?: ApiInventoryProductListParams,
): Promise<ApiInventoryProduct[]> {
  const { data } = await httpClient.get<ApiInventoryProduct[]>(ENDPOINTS.INVENTORY.PRODUCTS, {
    params,
  });
  return data;
}

export async function getInventoryProduct(id: string): Promise<ApiInventoryProduct> {
  const { data } = await httpClient.get<ApiInventoryProduct>(ENDPOINTS.INVENTORY.PRODUCT(id));
  return data;
}

export async function createInventoryProduct(
  body: ApiInventoryProductCreate,
): Promise<ApiInventoryProduct> {
  const { data } = await httpClient.post<ApiInventoryProduct>(ENDPOINTS.INVENTORY.PRODUCTS, body);
  return data;
}

export async function updateInventoryProduct(
  id: string,
  body: ApiInventoryProductUpdate,
): Promise<ApiInventoryProduct> {
  const { data } = await httpClient.patch<ApiInventoryProduct>(ENDPOINTS.INVENTORY.PRODUCT(id), body);
  return data;
}

export async function getStockLevel(id: string): Promise<ApiStockLevel> {
  const { data } = await httpClient.get<ApiStockLevel>(ENDPOINTS.INVENTORY.STOCK(id));
  return data;
}

export async function listStockLevels(): Promise<ApiStockLevelView[]> {
  const { data } = await httpClient.get<ApiStockLevelView[]>(ENDPOINTS.INVENTORY.LEVELS);
  return data;
}

export async function listProductMovements(productId: string): Promise<ApiStockMovement[]> {
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
  body: ApiStockMovementCreate | ApiStockAdjustmentCreate,
): Promise<ApiStockMovement> {
  const { data } = await httpClient.post<ApiStockMovement>(
    ENDPOINTS.INVENTORY.PRODUCT_ADJUST(productId),
    body,
  );
  return data;
}

export async function getInventoryValuation(): Promise<ApiValuationReport> {
  const { data } = await httpClient.get<ApiValuationReport>(ENDPOINTS.INVENTORY.VALUATION_REPORT);
  return data;
}

export async function listLowStockItems(): Promise<ApiLowStockItem[]> {
  const { data } = await httpClient.get<ApiLowStockItem[]>(ENDPOINTS.INVENTORY.LOW_STOCK_REPORT);
  return data;
}

export async function listProducts(limit = 100): Promise<ApiProduct[]> {
  return listInventoryProducts({ limit }) as Promise<ApiProduct[]>;
}

export async function getProduct(id: string): Promise<ApiProduct> {
  return getInventoryProduct(id) as Promise<ApiProduct>;
}

export async function createProduct(payload: ApiProductCreate): Promise<ApiProduct> {
  return createInventoryProduct(payload) as Promise<ApiProduct>;
}

export async function listMovements(id: string, limit = 50): Promise<ApiStockMovement[]> {
  const { data } = await httpClient.get<ApiStockMovement[]>(ENDPOINTS.INVENTORY.PRODUCT_MOVEMENTS(id), {
    params: { limit },
  });
  return data;
}

export async function recordMovement(
  id: string,
  payload: ApiMovementCreate,
): Promise<ApiStockMovement> {
  return applyStockMovement(id, payload as ApiStockMovementCreate);
}

export const listLevels = listStockLevels;
export const getValuation = getInventoryValuation;
export const listLowStock = listLowStockItems;
