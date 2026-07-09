// ─── Email preferences hooks ────────────────────────────────────────────────
// Read + toggle the signed-in user's suppressible email categories. The PUT
// returns the full updated set, so we seed the query cache from the mutation.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  getEmailPreferences,
  updateEmailPreference,
} from "@/lib/api/notifications";
import type { ApiEmailPreferences, ApiPreferenceUpdate } from "@/types/api";

const emailPrefsKey = ["notifications", "email-preferences"] as const;

export function useEmailPreferences() {
  return useQuery<ApiEmailPreferences>({
    queryKey: emailPrefsKey,
    queryFn: getEmailPreferences,
  });
}

export function useUpdateEmailPreference() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: ApiPreferenceUpdate) => updateEmailPreference(body),
    onSuccess: (data) => {
      queryClient.setQueryData(emailPrefsKey, data);
    },
  });
}
