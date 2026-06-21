// ─── Intelligence data hooks ────────────────────────────────────────────────────
// TanStack Query hooks over the read-only intelligence feed endpoints. Dashboard
// widgets (IntelligenceInsights, AiActionCenter) consume these instead of
// hardcoded mock arrays. The feeds are cheap reads over persisted orchestration
// runs, so polling on mount is fine.

import { useQuery } from "@tanstack/react-query";
import {
  listActions,
  listAgentTelemetry,
  listInsights,
  listNotifications,
} from "@/lib/api/intelligence";
import type {
  ApiActionFeedItem,
  ApiAgentTelemetry,
  ApiInsightFeedItem,
  ApiNotificationItem,
} from "@/types/api";

export const intelligenceKeys = {
  insights: ["intelligence", "insights"] as const,
  actions: ["intelligence", "actions"] as const,
  notifications: ["intelligence", "notifications"] as const,
  agents: ["intelligence", "agents"] as const,
};

export function useAiInsights() {
  return useQuery<ApiInsightFeedItem[]>({
    queryKey: intelligenceKeys.insights,
    queryFn: listInsights,
  });
}

export function useAiActions() {
  return useQuery<ApiActionFeedItem[]>({
    queryKey: intelligenceKeys.actions,
    queryFn: listActions,
  });
}

export function useNotifications() {
  return useQuery<ApiNotificationItem[]>({
    queryKey: intelligenceKeys.notifications,
    queryFn: listNotifications,
    refetchInterval: 30_000,
  });
}

export function useAgentTelemetry() {
  return useQuery<ApiAgentTelemetry[]>({
    queryKey: intelligenceKeys.agents,
    queryFn: listAgentTelemetry,
  });
}
