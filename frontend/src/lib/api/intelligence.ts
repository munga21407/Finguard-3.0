// ─── Intelligence API ──────────────────────────────────────────────────────────
// Thin wrappers around the two intelligence endpoints used by AgentChatWindow.
//
// POST /conversation   — dispatch a background LangGraph run, returns session_id
// GET  /conversation/{session_id}/status — poll until "completed" or "failed"
//
// The Axios request interceptor in http-client.ts automatically injects an
// Idempotency-Key UUID for every POST to /api/v1/intelligence/*, so callers
// here do not need to handle that header manually.

import httpClient from "@/lib/api/http-client";
import { ENDPOINTS } from "@/lib/api/endpoints";

// ── Request types ─────────────────────────────────────────────────────────────

export interface DispatchConversationPayload {
  message: string;
  context?: Record<string, unknown>;
}

// ── Response types — mirror backend Pydantic schemas exactly ──────────────────

/**
 * Returned by POST /conversation.
 * When `refreshing === true` the background task was queued and
 * `session_id` is the handle to poll for status.
 * When `refreshing === false` the artifact was served from cache.
 */
export interface ConversationDispatchResponse {
  session_id: string | null;
  refreshing: boolean;
  artifact: Record<string, unknown> | null;
}

/**
 * Returned by GET /conversation/{session_id}/status.
 *
 * status: "pending"   — task is in-flight
 *         "completed" — graph finished; artifact_id is populated
 *         "failed"    — graph raised; detail contains the error
 *
 * `answer` is not returned by the current backend but is typed here for
 * forward-compatibility — if the backend is later extended to embed the
 * answer in the status payload this field will be populated automatically.
 */
export interface ConversationStatusResponse {
  session_id: string;
  status: "pending" | "completed" | "failed";
  artifact_id: string | null;
  detail: string | null;
  answer?: string;
}

// ── API functions ─────────────────────────────────────────────────────────────

/**
 * Dispatch a natural-language query to Agent D as a background LangGraph run.
 * Returns immediately with a `session_id`; use `checkConversationStatus` to
 * poll for the result.
 */
export async function dispatchConversation(
  payload: DispatchConversationPayload
): Promise<ConversationDispatchResponse> {
  const { data } = await httpClient.post<ConversationDispatchResponse>(
    ENDPOINTS.INTELLIGENCE.CONVERSATION,
    {
      intent: payload.message,
      context: payload.context ?? {},
      force_refresh: true,
      mode: "insights",
    }
  );
  return data;
}

/**
 * Check the execution status of a running Agent D session.
 * Poll this until `status` is `"completed"` or `"failed"`.
 */
export async function checkConversationStatus(
  sessionId: string
): Promise<ConversationStatusResponse> {
  const { data } = await httpClient.get<ConversationStatusResponse>(
    ENDPOINTS.INTELLIGENCE.CONVERSATION_STATUS(sessionId)
  );
  return data;
}
