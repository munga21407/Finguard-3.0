// ─── Email delivery admin hooks ──────────────────────────────────────────────
// KPIs + dead-letter queue with replay. Manager/admin surface (server enforces
// user:manage; the panel is only rendered for admins).

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  getDeadLetters,
  getEmailKpis,
  replayDeadLetter,
} from "@/lib/api/notifications";
import type { ApiEmailDeadLetterPage, ApiEmailKpis } from "@/types/api";

const emailAdminKeys = {
  kpis: ["notifications", "email", "kpis"] as const,
  deadLetters: ["notifications", "email", "dead-letters"] as const,
};

export function useEmailKpis() {
  return useQuery<ApiEmailKpis>({
    queryKey: emailAdminKeys.kpis,
    queryFn: getEmailKpis,
  });
}

export function useDeadLetters() {
  return useQuery<ApiEmailDeadLetterPage>({
    queryKey: emailAdminKeys.deadLetters,
    queryFn: getDeadLetters,
  });
}

export function useReplayDeadLetter() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => replayDeadLetter(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: emailAdminKeys.deadLetters });
      queryClient.invalidateQueries({ queryKey: emailAdminKeys.kpis });
    },
  });
}
