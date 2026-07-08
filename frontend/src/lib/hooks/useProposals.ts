// ─── Agent action proposals (human-in-the-loop) ──────────────────────────────
// TanStack Query hooks over the agent-action approval queue. A reviewer with the
// action's domain permission (e.g. inventory:adjust for a stock adjustment)
// approves or rejects a proposal an agent made. Approving applies the underlying
// write, so we invalidate the inventory caches on success. The backend blocks the
// person who triggered the agent from approving their own action.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  approveAgentProposal,
  getAgentProposals,
  rejectAgentProposal,
} from "@/lib/api/intelligence";
import { inventoryKeys } from "@/lib/hooks/useInventory";
import type { ApiAgentActionProposal } from "@/types/api";

export const proposalKeys = {
  pending: ["intelligence", "proposals", "pending"] as const,
};

export function useAgentProposals() {
  return useQuery<ApiAgentActionProposal[]>({
    queryKey: proposalKeys.pending,
    queryFn: getAgentProposals,
  });
}

/** Approve (applies the write) or reject a pending agent proposal. */
export function useTransitionProposal() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, action }: { id: string; action: "approve" | "reject" }) =>
      action === "approve" ? approveAgentProposal(id) : rejectAgentProposal(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: proposalKeys.pending });
      // Approving an adjustment mutates stock — refresh the inventory reads.
      queryClient.invalidateQueries({ queryKey: inventoryKeys.levels });
      queryClient.invalidateQueries({ queryKey: inventoryKeys.valuation });
      queryClient.invalidateQueries({ queryKey: inventoryKeys.lowStock });
    },
  });
}
