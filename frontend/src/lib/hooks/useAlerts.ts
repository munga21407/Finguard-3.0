// ─── Alerts data hooks ──────────────────────────────────────────────────────────
// TanStack Query hooks over the alerts endpoints. Dashboard alert widgets consume
// these instead of hardcoded arrays; the resolve mutation invalidates the lists.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  getAlertKpis,
  listAlerts,
  listResolvedAlerts,
  resolveAlert,
} from "@/lib/api/alerts";
import type { ApiAlert, ApiAlertKpis } from "@/types/api";

export const alertKeys = {
  active: ["alerts", "active"] as const,
  resolved: ["alerts", "resolved"] as const,
  kpis: ["alerts", "kpis"] as const,
};

export function useAlerts() {
  return useQuery<ApiAlert[]>({ queryKey: alertKeys.active, queryFn: listAlerts });
}

export function useResolvedAlerts() {
  return useQuery<ApiAlert[]>({ queryKey: alertKeys.resolved, queryFn: listResolvedAlerts });
}

export function useAlertKpis() {
  return useQuery<ApiAlertKpis>({ queryKey: alertKeys.kpis, queryFn: getAlertKpis });
}

export function useResolveAlert() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, note }: { id: string; note?: string }) => resolveAlert(id, note),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: alertKeys.active });
      queryClient.invalidateQueries({ queryKey: alertKeys.resolved });
      queryClient.invalidateQueries({ queryKey: alertKeys.kpis });
    },
  });
}
