import httpClient from "@/lib/api/http-client";
import { ENDPOINTS } from "@/lib/api/endpoints";

export async function listInventoryProducts() {
  return httpClient.get(ENDPOINTS.INVENTORY.PRODUCTS);
}

export async function createInventoryProduct(payload: Record<string, unknown>) {
  return httpClient.post(ENDPOINTS.INVENTORY.PRODUCTS, payload);
}

export async function recordInventoryMovement(productId: string, payload: Record<string, unknown>) {
  return httpClient.post(ENDPOINTS.INVENTORY.MOVEMENTS(productId), payload);
}
