// ─── API Type Bridge ───────────────────────────────────────────────────────────
// All exported names here are derived from the auto-generated OpenAPI schema at
// @/lib/api/generated/schema.d.ts.  Consumers import from *this* file, not
// directly from the generated file — that way, if `openapi-typescript` ever
// changes its internal output structure, only this file needs updating.
//
// Refreshing the generated schema:
//   npm run sync-types              # requires the FastAPI backend to be running
//   OPENAPI_URL=http://staging:8000 npm run sync-types   # point at any env
//
// Type naming convention:
//   Api<Domain><Model>  e.g. ApiInvoice, ApiCustomer, ApiOrchestrationResponse
//
// The `UserRole` in this file is lowercase ("admin", "owner", …) — that is the
// raw wire value from the backend StrEnum.  auth-context.tsx normalises it to
// uppercase when hydrating React state.  Use `User` from @/types/auth for the
// post-normalisation shape used in the UI; use ApiUser only when typing raw
// HTTP response bodies.

import type { components, paths } from "@/lib/api/generated/schema";

// ── Internal convenience alias ────────────────────────────────────────────────
type S = components["schemas"];

// ── Generic path-level helpers ────────────────────────────────────────────────
// Derive precise request / response body types directly from the path contract.
// This is the highest-fidelity typing available: if the backend changes a field
// the diff will appear in schema.d.ts and propagate here automatically.
//
// Usage examples:
//
//   // Body sent to POST /api/v1/finance/invoices
//   type CreateInvoiceBody = ApiRequestBody<"/api/v1/finance/invoices", "post">;
//
//   // 201 response from POST /api/v1/finance/invoices
//   type NewInvoice = ApiResponseBody<"/api/v1/finance/invoices", "post", 201>;
//
//   // 200 response from GET /api/v1/intelligence/conversation/{session_id}/status
//   type PollStatus = ApiResponseBody<
//     "/api/v1/intelligence/conversation/{session_id}/status",
//     "get"
//   >;

export type ApiRequestBody<
  P extends keyof paths,
  M extends keyof paths[P],
> = paths[P][M] extends { requestBody: { content: { "application/json": infer B } } }
  ? B
  : never;

export type ApiResponseBody<
  P extends keyof paths,
  M extends keyof paths[P],
  Status extends number = 200,
> = paths[P][M] extends {
  responses: { [K in Status]: { content: { "application/json": infer B } } };
}
  ? B
  : never;

// Re-export root types for consumers that need to traverse the full schema map.
export type { components as ApiComponents, paths as ApiPaths };

// ── Identity ──────────────────────────────────────────────────────────────────
/** Wire-format role — lowercase.  See @/types/auth for the UI-facing normalised version. */
export type ApiUserRole     = S["UserRole"];
export type ApiUser         = S["UserResponse"];
export type ApiUserCreate   = S["UserCreate"];
export type ApiTokenResponse = S["TokenResponse"];

// ── CRM ───────────────────────────────────────────────────────────────────────
export type ApiCustomer       = S["CustomerResponse"];
export type ApiCustomerCreate = S["CustomerCreate"];
export type ApiCustomerUpdate = S["CustomerUpdate"];
export type ApiCustomerStatus = S["CustomerStatus"];
export type ApiCustomerType   = S["CustomerType"];

// ── Finance ───────────────────────────────────────────────────────────────────
export type ApiInvoice           = S["InvoiceResponse"];
export type ApiInvoiceCreate     = S["InvoiceCreate"];
export type ApiInvoiceUpdate     = S["InvoiceUpdate"];
export type ApiInvoiceStatus     = S["InvoiceStatus"];
export type ApiLedgerEntry       = S["LedgerEntryResponse"];
export type ApiLedgerEntryCreate = S["LedgerEntryCreate"];
export type ApiBudget            = S["BudgetResponse"];
export type ApiBudgetCreate      = S["BudgetCreate"];
export type ApiExpense           = S["ExpenseResponse"];
export type ApiExpenseCreate     = S["ExpenseCreate"];
export type ApiPayment           = S["PaymentResponse"];
export type ApiPaymentCreate     = S["PaymentCreate"];
export type ApiTransactionType   = S["TransactionType"];
export type ApiVaultType         = S["VaultType"];

// ── Intelligence ──────────────────────────────────────────────────────────────
export type ApiInsightRequest        = S["InsightRequest"];
export type ApiActionRequest         = S["ActionRequest"];
export type ApiOrchestrationResponse = S["OrchestrationResponse"];
export type ApiIntentRequest         = S["IntentRequest"];
export type ApiIntentResponse        = S["IntentResponse"];
export type ApiConversationRequest   = S["ConversationRequest"];
export type ApiConversationResponse  = S["ConversationResponse"];
export type ApiTaskStatus            = S["TaskStatusResponse"];
export type ApiAgentRunStatus        = S["AgentRunStatus"];
export type ApiAgentRunResponse      = S["AgentRunResponse"];

// ── Agent structured outputs ──────────────────────────────────────────────────
export type ApiExtractedInvoice  = S["ExtractedInvoice"];
export type ApiExtractedLineItem = S["ExtractedLineItem"];
export type ApiWatchdogAnalysis  = S["WatchdogAnalysis"];
export type ApiCashFlowForecast  = S["CashFlowForecast"];
export type ApiRegimeAnalysis    = S["RegimeAnalysis"];
export type ApiForecastDataPoint = S["ForecastDataPoint"];
export type ApiAgentFOutput      = S["AgentFOutput"];
export type ApiAgentGOutput      = S["AgentGOutput"];

// ── Validation errors ─────────────────────────────────────────────────────────
export type ApiValidationError = S["HTTPValidationError"];
