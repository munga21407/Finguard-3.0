// ─── Audit API ────────────────────────────────────────────────────────────────
// Typed wrappers over the audit / activity-log endpoints (managers+).
//
// Types are hand-written here rather than derived from the generated
// `schema.d.ts` so the frontend stays buildable independently of an OpenAPI
// regeneration; they mirror `AuditLogResponse` / `AuditLogPage` / `AuditKpis`
// in backend `src/domains/audit/schemas.py`. Keep them in sync if those change.

import httpClient from "@/lib/api/http-client";
import { ENDPOINTS } from "@/lib/api/endpoints";

export type AuditActorType = "user" | "agent" | "system";
export type AuditOutcome = "success" | "failure" | "denied";

export interface ApiAuditLog {
  id: string;
  actor_type: AuditActorType;
  actor_id: string | null;
  actor_label: string | null;
  action: string;
  resource_type: string;
  resource_id: string | null;
  outcome: AuditOutcome;
  ip_address: string | null;
  request_id: string | null;
  metadata_payload: Record<string, unknown>;
  created_at: string;
}

export interface ApiAuditLogPage {
  items: ApiAuditLog[];
  total: number;
  limit: number;
  offset: number;
}

export interface ApiAuditKpis {
  total: number;
  last_24h: number;
  failures_last_24h: number;
  denied_last_24h: number;
}

export interface AuditQuery {
  actorId?: string;
  action?: string;
  resourceType?: string;
  resourceId?: string;
  outcome?: AuditOutcome;
  since?: string;
  until?: string;
  limit?: number;
  offset?: number;
}

export async function listAuditLogs(query: AuditQuery = {}): Promise<ApiAuditLogPage> {
  // Map the camelCase query to the snake_case API params, omitting empties so the
  // backend applies its own defaults (limit=50, offset=0).
  const params: Record<string, string | number> = {};
  if (query.actorId) params.actor_id = query.actorId;
  if (query.action) params.action = query.action;
  if (query.resourceType) params.resource_type = query.resourceType;
  if (query.resourceId) params.resource_id = query.resourceId;
  if (query.outcome) params.outcome = query.outcome;
  if (query.since) params.since = query.since;
  if (query.until) params.until = query.until;
  if (query.limit != null) params.limit = query.limit;
  if (query.offset != null) params.offset = query.offset;

  const { data } = await httpClient.get<ApiAuditLogPage>(ENDPOINTS.AUDIT.ROOT, { params });
  return data;
}

export async function getAuditKpis(): Promise<ApiAuditKpis> {
  const { data } = await httpClient.get<ApiAuditKpis>(ENDPOINTS.AUDIT.KPIS);
  return data;
}
