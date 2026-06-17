// ─── Health API ─────────────────────────────────────────────────────────────
// Reads the backend readiness probe. The endpoint returns HTTP 503 (not an
// error envelope) when a hard dependency is down, so we accept that status and
// parse the body either way — "degraded" is a valid, reportable result.

import httpClient from "@/lib/api/http-client";
import { ENDPOINTS } from "@/lib/api/endpoints";

export type DependencyName = "postgres" | "redis" | "mongodb" | "rabbitmq";

export interface ReadinessResult {
  status: "ready" | "degraded";
  checks: Record<DependencyName, string>;
}

export async function getReadiness(): Promise<ReadinessResult> {
  const { data } = await httpClient.get<ReadinessResult>(ENDPOINTS.HEALTH.READY, {
    // 503 is the documented "degraded" response — treat it as success so we can
    // surface which dependency failed instead of throwing.
    validateStatus: (status) => status === 200 || status === 503,
  });
  return data;
}
