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
import type {
  ApiActionFeedItem,
  ApiAgentTelemetry,
  ApiInsightFeedItem,
  ApiNotificationItem,
} from "@/types/api";

// ── Generative UI contract ────────────────────────────────────────────────────

/** Sprint 6 key-finding badge emitted by CompositeGenUIPayload on the backend. */
export interface KeyFinding {
  metric: string;
  value: string;
}

/**
 * A structured UI payload emitted by an agent and embedded in the chat stream.
 * `component_id` must match a key in GenUiRegistry; `props` are forwarded
 * verbatim to the mounted component; `fallback_text` is shown when the
 * component cannot be resolved or rendered.
 *
 * Sprint 6: composite agents also embed `findings: KeyFinding[]` inside `props`
 * via `CompositeGenUIPayload.to_gen_ui_payload()`.  The chat router uses the
 * presence of that key to select `CompositeInsightBlock` instead of `GenUiBlock`.
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

// ── Agent A — invoice extraction ──────────────────────────────────────────────

/** One extracted line item (mirrors backend ExtractedLineItem). */
export interface ExtractedLineItem {
  description: string;
  quantity: number;
  unit_price: number;
  total: number;
}

/** Agent A's structured invoice extraction (mirrors backend ExtractedInvoice). */
export interface ExtractedInvoice {
  vendor: string | null;
  customer: string | null;
  invoice_number: string | null;
  issue_date: string | null;
  due_date: string | null;
  currency: string;
  subtotal: number | null;
  tax: number | null;
  total: number | null;
  line_items: ExtractedLineItem[];
  confidence: number;
}

interface IntentResponse {
  session_id: string;
  intent: string;
  invoice_payload: ExtractedInvoice | null;
  hub_artifact_id: string | null;
}

// ── Receipt Scanner — multimodal OCR ──────────────────────────────────────────

/** Structured receipt OCR output (mirrors backend ReceiptExtraction). */
export interface ReceiptExtraction {
  merchant_name: string | null;
  date: string | null;
  total_amount: number | null;
  currency: string;
  kra_pin: string | null;
  line_items: string[];
  confidence: number;
}

/** Response of POST /intelligence/receipts/scan (mirrors ReceiptScanResponse). */
export interface ReceiptScanResult {
  session_id: string;
  extraction: ReceiptExtraction;
  suggested_category: string;
  error: string | null;
}

/**
 * Upload a receipt image and run Gemini vision OCR + categorisation.
 * Returns the extracted fields and a suggested expense category for the user
 * to review before persisting via createReceiptExpense().
 */
export async function scanReceipt(file: File): Promise<ReceiptScanResult> {
  const form = new FormData();
  form.append("file", file);
  // Let the browser set the multipart boundary; overriding Content-Type breaks it.
  const { data } = await httpClient.post<ReceiptScanResult>(
    ENDPOINTS.INTELLIGENCE.RECEIPT_SCAN,
    form,
    { headers: { "Content-Type": "multipart/form-data" } }
  );
  return data;
}

/**
 * Run Agent A over a free-text description and return the structured invoice
 * extraction (or null when the model could not extract one). The caller maps
 * this into the editable invoice form for review before saving.
 */
export async function extractInvoice(
  userInput: string
): Promise<ExtractedInvoice | null> {
  const { data } = await httpClient.post<IntentResponse>(
    ENDPOINTS.INTELLIGENCE.INTENT,
    { user_input: userInput, intent: "GENERATE_INVOICE" }
  );
  return data.invoice_payload;
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

// ── Dashboard feeds ─────────────────────────────────────────────────────────────
// Cheap structured reads over persisted orchestration runs. Unlike the POST
// /ai-insights & /ai-actions endpoints these do NOT run the LLM — they just read
// the AgentRun log, so dashboard widgets can poll them on mount.

/** Recent read-only analysis items for the IntelligenceInsights widget. */
export async function listInsights(): Promise<ApiInsightFeedItem[]> {
  const { data } = await httpClient.get<ApiInsightFeedItem[]>(
    ENDPOINTS.INTELLIGENCE.INSIGHTS_FEED
  );
  return data;
}

/** Recent actionable items for the AiActionCenter widget. */
export async function listActions(): Promise<ApiActionFeedItem[]> {
  const { data } = await httpClient.get<ApiActionFeedItem[]>(
    ENDPOINTS.INTELLIGENCE.ACTIONS_FEED
  );
  return data;
}

/** Recent agent activity for the top-bar notification bell. */
export async function listNotifications(): Promise<ApiNotificationItem[]> {
  const { data } = await httpClient.get<ApiNotificationItem[]>(
    ENDPOINTS.INTELLIGENCE.NOTIFICATIONS
  );
  return data;
}

/** Per-agent run statistics for the agent-status widgets. */
export async function listAgentTelemetry(): Promise<ApiAgentTelemetry[]> {
  const { data } = await httpClient.get<ApiAgentTelemetry[]>(
    ENDPOINTS.INTELLIGENCE.AGENTS
  );
  return data;
}

// ── GenUI error telemetry ──────────────────────────────────────────────────────

export interface GenUiErrorReport {
  component_id: string;
  message: string;
  component_stack?: string | null;
  pathname?: string | null;
}

/**
 * Report a GenUI widget render crash to operational telemetry. Fire-and-forget:
 * the dashboard must never break because the error report failed, so callers
 * should swallow rejections (the boundary already shows its fallback UI).
 */
export async function reportGenUiError(report: GenUiErrorReport): Promise<void> {
  await httpClient.post(ENDPOINTS.INTELLIGENCE.GENUI_ERROR, report);
}
