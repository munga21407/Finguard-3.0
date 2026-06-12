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

// ── Generative UI contract ────────────────────────────────────────────────────

/**
 * A structured UI payload emitted by an agent and embedded in the chat stream.
 * `component_id` must match a key in GenUiRegistry; `props` are forwarded
 * verbatim to the mounted component; `fallback_text` is shown when the
 * component cannot be resolved or rendered.
 */
export interface GenUIPayload {
  component_id: string;
  props: Record<string, unknown>;
  fallback_text: string;
}

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
  gen_ui_payloads?: GenUIPayload[];
}

/**
 * Returned by GET /conversation/{session_id}/status.
 *
 * status: "pending"   — task is queued, no node has started
 *         "running"   — graph mid-execution; active_node identifies
 *                       the agent currently compiling data, e.g.
 *                       "running:b_classifier" or "running:e_watchdog"
 *         "completed" — graph finished; artifact_id is set;
 *                       gen_ui_payloads carries structured UI components
 *         "failed"    — graph raised; detail contains the truncated error
 *
 * `answer` is typed for forward-compatibility — the backend may embed it
 * directly in the status payload in a future sprint.
 */
export interface ConversationStatusResponse {
  session_id: string;
  status: "pending" | "running" | "completed" | "failed";
  artifact_id: string | null;
  /** Which agent node is actively compiling, e.g. "running:b_classifier". */
  active_node: string | null;
  /** Structured GenUI payloads ready to mount in the chat window. */
  gen_ui_payloads: GenUIPayload[];
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
