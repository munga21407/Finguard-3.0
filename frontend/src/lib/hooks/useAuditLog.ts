// ─── Audit log data hooks ───────────────────────────────────────────────────────
// TanStack Query hooks over the audit endpoints backing the Operations → Activity
// Log view. The list query is keyed by its filter so paging/filtering refetches.

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import {
  getAuditKpis,
  listAuditLogs,
  type ApiAuditKpis,
  type ApiAuditLogPage,
  type AuditQuery,
} from "@/lib/api/audit";

export const auditKeys = {
  list: (query: AuditQuery) => ["audit", "list", query] as const,
  kpis: ["audit", "kpis"] as const,
};

export function useAuditLogs(query: AuditQuery = {}) {
  return useQuery<ApiAuditLogPage>({
    queryKey: auditKeys.list(query),
    queryFn: () => listAuditLogs(query),
    // Keep the previous page visible while the next loads — avoids a flash of
    // empty table when paging or changing filters.
    placeholderData: keepPreviousData,
  });
}

export function useAuditKpis() {
  return useQuery<ApiAuditKpis>({ queryKey: auditKeys.kpis, queryFn: getAuditKpis });
}
