// ─── Inventory (Stock Management) API ───────────────────────────────────────────
// Typed wrappers over the /inventory endpoints, mirroring finance.ts. Types come
// from the generated OpenAPI schema via @/types/api, so a backend contract change
// surfaces here at compile time.

import { ENDPOINTS } from "@/lib/api/endpoints";
import httpClient from "@/lib/api/http-client";
import type {
  ApiLowStockItem,
  ApiMovementCreate,
  ApiProduct,
  ApiProductCreate,
  ApiStockAdjustmentCreate,
  ApiStockLevel,
  ApiStockLevelView,
  ApiStockMovement,
  ApiValuationReport,
} from "@/types/api";

export async function listProducts(limit = 100): Promise<ApiProduct[]> {
  const { data } = await httpClient.get<ApiProduct[]>(ENDPOINTS.INVENTORY.PRODUCTS, {
    params: { limit },
  });
  return data;
}

export async function getProduct(id: string): Promise<ApiProduct> {
  const { data } = await httpClient.get<ApiProduct>(ENDPOINTS.INVENTORY.PRODUCT(id));
  return data;
}

export async function createProduct(payload: ApiProductCreate): Promise<ApiProduct> {
  const { data } = await httpClient.post<ApiProduct>(ENDPOINTS.INVENTORY.PRODUCTS, payload);
  return data;
}

export async function getStockLevel(id: string): Promise<ApiStockLevel> {
  const { data } = await httpClient.get<ApiStockLevel>(ENDPOINTS.INVENTORY.STOCK(id));
  return data;
}

export async function listMovements(id: string, limit = 50): Promise<ApiStockMovement[]> {
  const { data } = await httpClient.get<ApiStockMovement[]>(ENDPOINTS.INVENTORY.MOVEMENTS(id), {
    params: { limit },
  });
  return data;
}

export async function recordMovement(
  id: string,
  payload: ApiMovementCreate,
): Promise<ApiStockMovement> {
  const { data } = await httpClient.post<ApiStockMovement>(
    ENDPOINTS.INVENTORY.MOVEMENTS(id),
    payload,
  );
  return data;
}

export async function adjustStock(
  id: string,
  payload: ApiStockAdjustmentCreate,
): Promise<ApiStockMovement> {
  const { data } = await httpClient.post<ApiStockMovement>(ENDPOINTS.INVENTORY.ADJUST(id), payload);
  return data;
}

export async function listLevels(): Promise<ApiStockLevelView[]> {
  const { data } = await httpClient.get<ApiStockLevelView[]>(ENDPOINTS.INVENTORY.LEVELS);
  return data;
}

export async function getValuation(): Promise<ApiValuationReport> {
  const { data } = await httpClient.get<ApiValuationReport>(ENDPOINTS.INVENTORY.VALUATION);
  return data;
}

export async function listLowStock(): Promise<ApiLowStockItem[]> {
  const { data } = await httpClient.get<ApiLowStockItem[]>(ENDPOINTS.INVENTORY.LOW_STOCK);
  return data;
}
