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
// Login/refresh now return only the access token in the body; the refresh token
// is delivered as an HttpOnly cookie (see auth-client.ts).
export type ApiAccessTokenResponse = S["AccessTokenResponse"];

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
export type ApiReceiptExpenseCreate = S["ReceiptExpenseCreate"];
export type ApiPayment           = S["PaymentResponse"];
export type ApiPaymentCreate     = S["PaymentCreate"];
export type ApiTransactionType   = S["TransactionType"];
export type ApiVaultType         = S["VaultType"];
// Accounts-payable approval queue (maker-checker state machine on expenses).
export type ApiPayable              = S["PayableResponse"];
export type ApiPayableCreate        = S["PayableCreate"];
export type ApiPayableQueue         = S["PayableQueueResponse"];
export type ApiPayableQueueKpis     = S["PayableQueueKpis"];
export type ApiExpenseApprovalStatus = S["ExpenseApprovalStatus"];
// Invoice-lifecycle → settlement-rail Sankey for the Overview dashboard.
export type ApiReconciliationFlow = S["ReconciliationFlowResponse"];
export type ApiSankeyNode         = S["SankeyNode"];
export type ApiSankeyLink         = S["SankeyLink"];
// Bank statement reconciliation (Agent C source).
export type ApiBankStatementImport = S["BankStatementLineImport"];
export type ApiBankStatementLine   = S["BankStatementLineResponse"];
// Treasury — per-vault balances + internal transfers.
export type ApiVaultTransfer       = S["VaultTransferResponse"];
export type ApiVaultTransferCreate = S["VaultTransferCreate"];
export type ApiVaultBalance        = S["VaultBalance"];
export type ApiVaultBalances       = S["VaultBalancesResponse"];
// CoreReports — deterministic financial reports (P&L / cash-flow / tax).
export type ApiReportType          = S["ReportType"];
export type ApiReportMetric        = S["ReportMetric"];
export type ApiReportLine          = S["ReportLine"];
export type ApiReportSeriesPoint   = S["ReportSeriesPoint"];
export type ApiFinancialReport     = S["FinancialReport"];
export type ApiReportCatalogItem   = S["ReportCatalogItem"];
export type ApiReportCatalog       = S["ReportCatalogResponse"];

// ── Intelligence ──────────────────────────────────────────────────────────────
export type ApiInsightRequest        = S["InsightRequest"];
export type ApiActionRequest         = S["ActionRequest"];
export type ApiOrchestrationResponse = S["OrchestrationResponse"];
export type ApiIntentRequest         = S["IntentRequest"];
export type ApiIntentResponse        = S["IntentResponse"];
export type ApiReceiptScanResponse   = S["ReceiptScanResponse"];
export type ApiReceiptExtraction     = S["ReceiptExtraction"];
export type ApiConversationRequest   = S["ConversationRequest"];
export type ApiConversationResponse  = S["ConversationResponse"];
export type ApiTaskStatus            = S["TaskStatusResponse"];
// Dashboard feeds — cheap structured reads over persisted orchestration runs.
export type ApiInsightFeedItem       = S["InsightFeedItem"];
export type ApiActionFeedItem        = S["ActionFeedItem"];
export type ApiNotificationItem      = S["NotificationItem"];
export type ApiAgentTelemetry        = S["AgentTelemetry"];
// Admin: KRA knowledge-base document ingestion result.
export type ApiKnowledgeIngestResponse = S["KnowledgeIngestResponse"];

// ── Alerts ──────────────────────────────────────────────────────────────────────
export type ApiAlert         = S["AlertResponse"];
export type ApiAlertCreate   = S["AlertCreate"];
export type ApiAlertKpis     = S["AlertKpis"];
export type ApiAlertType     = S["AlertType"];
export type ApiAlertSeverity = S["AlertSeverity"];
export type ApiAlertStatus   = S["AlertStatus"];

// Inventory / stock management
// Hand-written until the backend inventory domain is added and schema.d.ts is
// regenerated. Keep these names stable so callers can switch to generated
// schema aliases without changing imports.
export type ApiUnitOfMeasure =
  | "each"
  | "kg"
  | "litre"
  | "metre"
  | "box"
  | "pack";

export type ApiStockMovementType =
  | "receipt"
  | "issue"
  | "sale"
  | "return_in"
  | "adjustment"
  | "transfer";

export type ApiStockMovementReason =
  | "purchase"
  | "sale"
  | "damage"
  | "theft"
  | "stock_take"
  | "expiry"
  | "correction"
  | "other";

export interface ApiStockLevel {
  id: string;
  product_id: string;
  location_id: string | null;
  quantity_on_hand: string;
  quantity_reserved: string;
  average_cost: string;
  updated_at: string;
}

export interface ApiInventoryProduct {
  id: string;
  sku: string;
  name: string;
  description: string | null;
  unit: ApiUnitOfMeasure;
  category: string | null;
  cost_price: string;
  selling_price: string;
  reorder_level: string;
  reorder_quantity: string;
  barcode: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
  stock_level?: ApiStockLevel | null;
}

export interface ApiInventoryProductCreate {
  sku: string;
  name: string;
  description?: string | null;
  unit: ApiUnitOfMeasure;
  category?: string | null;
  cost_price: string;
  selling_price: string;
  reorder_level: string;
  reorder_quantity: string;
  barcode?: string | null;
}

export type ApiInventoryProductUpdate = Partial<ApiInventoryProductCreate> & {
  is_active?: boolean;
};

export interface ApiInventoryProductListParams {
  limit?: number;
  offset?: number;
  category?: string;
  low_stock?: boolean;
  q?: string;
}

export interface ApiStockMovementCreate {
  product_id?: string;
  location_id?: string | null;
  movement_type: ApiStockMovementType;
  reason?: ApiStockMovementReason | null;
  quantity: string;
  unit_cost?: string | null;
  reference_type?: string | null;
  reference_id?: string | null;
  note?: string | null;
}

export interface ApiStockMovement {
  id: string;
  product_id: string;
  location_id: string | null;
  sequence: number;
  movement_type: ApiStockMovementType;
  reason: ApiStockMovementReason | null;
  quantity: string;
  unit_cost: string | null;
  balance_after: string;
  reference_type: string | null;
  reference_id: string | null;
  note: string | null;
  created_by: string | null;
  created_at: string;
}

export interface ApiValuationReportItem {
  product_id: string;
  sku: string;
  name: string;
  category: string | null;
  quantity_on_hand: string;
  average_cost: string;
  value: string;
}

export interface ApiValuationReportCategory {
  category: string | null;
  value: string;
}

export interface ApiValuationReport {
  total_value: string;
  by_category: ApiValuationReportCategory[];
  items: ApiValuationReportItem[];
}

export interface ApiLowStockItem {
  product_id: string;
  sku: string;
  name: string;
  category: string | null;
  quantity_on_hand: string;
  reorder_level: string;
  reorder_quantity: string;
  unit: ApiUnitOfMeasure;
}

// NOTE: Agent structured-output models (ExtractedInvoice, WatchdogAnalysis,
// CashFlowForecast, AgentF/G outputs, AgentRun*, etc.) are intentionally NOT
// aliased here.  They are carried inside endpoint responses as `dict[str, Any]`
// (e.g. IntentResponse.invoice_payload, TaskStatusResponse.gen_ui_payloads), so
// FastAPI does not emit them as named OpenAPI components.  The frontend types
// for those payloads live as hand-written interfaces in lib/api/intelligence.ts
// (e.g. ExtractedInvoice, ReceiptExtraction) where they can be shaped to what
// the UI actually consumes.

// ── Validation errors ─────────────────────────────────────────────────────────
export type ApiValidationError = S["HTTPValidationError"];
