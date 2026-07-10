// ─── Notifications API ──────────────────────────────────────────────────────
// Email preferences: which suppressible categories (approval / reminder) the
// signed-in user has opted out of.

import httpClient from "@/lib/api/http-client";
import { ENDPOINTS } from "@/lib/api/endpoints";
import type {
  ApiEmailDeadLetterPage,
  ApiEmailKpis,
  ApiEmailPreferences,
  ApiPreferenceUpdate,
} from "@/types/api";

export async function getEmailPreferences(): Promise<ApiEmailPreferences> {
  const { data } = await httpClient.get<ApiEmailPreferences>(
    ENDPOINTS.NOTIFICATIONS.PREFERENCES,
  );
  return data;
}

export async function updateEmailPreference(
  body: ApiPreferenceUpdate,
): Promise<ApiEmailPreferences> {
  const { data } = await httpClient.put<ApiEmailPreferences>(
    ENDPOINTS.NOTIFICATIONS.PREFERENCES,
    body,
  );
  return data;
}

// ── Delivery admin (user:manage) ─────────────────────────────────────────────

export async function getEmailKpis(): Promise<ApiEmailKpis> {
  const { data } = await httpClient.get<ApiEmailKpis>(
    ENDPOINTS.NOTIFICATIONS.EMAIL_KPIS,
  );
  return data;
}

export async function getDeadLetters(): Promise<ApiEmailDeadLetterPage> {
  const { data } = await httpClient.get<ApiEmailDeadLetterPage>(
    ENDPOINTS.NOTIFICATIONS.EMAIL_DEAD_LETTERS,
  );
  return data;
}

export async function replayDeadLetter(id: string): Promise<void> {
  await httpClient.post(ENDPOINTS.NOTIFICATIONS.EMAIL_REPLAY(id));
}
