// ─── Alerts API ───────────────────────────────────────────────────────────────
// Typed wrappers over the alerts endpoints backing the alerts dashboard widgets.

import httpClient from "@/lib/api/http-client";
import { ENDPOINTS } from "@/lib/api/endpoints";
import type { ApiAlert, ApiAlertKpis } from "@/types/api";

export async function listAlerts(): Promise<ApiAlert[]> {
  const { data } = await httpClient.get<ApiAlert[]>(ENDPOINTS.ALERTS.ROOT);
  return data;
}

export async function listResolvedAlerts(): Promise<ApiAlert[]> {
  const { data } = await httpClient.get<ApiAlert[]>(ENDPOINTS.ALERTS.RESOLVED);
  return data;
}

export async function getAlertKpis(): Promise<ApiAlertKpis> {
  const { data } = await httpClient.get<ApiAlertKpis>(ENDPOINTS.ALERTS.KPIS);
  return data;
}

export async function resolveAlert(
  id: string,
  resolutionNote?: string,
): Promise<ApiAlert> {
  const { data } = await httpClient.post<ApiAlert>(ENDPOINTS.ALERTS.RESOLVE(id), {
    resolution_note: resolutionNote ?? null,
  });
  return data;
}
