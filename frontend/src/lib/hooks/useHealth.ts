// ─── Health hook ────────────────────────────────────────────────────────────
// Polls the readiness probe so the Operations page reflects live dependency
// state. Refetches on an interval and on window focus.

import { useQuery } from "@tanstack/react-query";
import { getReadiness, type ReadinessResult } from "@/lib/api/health";

export const healthKeys = {
  readiness: ["health", "readiness"] as const,
};

export function useReadiness() {
  return useQuery<ReadinessResult>({
    queryKey: healthKeys.readiness,
    queryFn: getReadiness,
    refetchInterval: 15_000,
    staleTime: 10_000,
  });
}
