// ─── API Endpoints ────────────────────────────────────────────────────────────

export const ENDPOINTS = {
  // Identity
  AUTH: {
    LOGIN: "/api/v1/identity/token",
    REGISTER: "/api/v1/identity/register",
    REFRESH: "/api/v1/identity/token/refresh",
    LOGOUT: "/api/v1/identity/logout",
    ME: "/api/v1/identity/me",
  },

  // Finance
  FINANCE: {
    LEDGER: "/api/v1/finance/ledger",
    INVOICES: "/api/v1/finance/invoices",
    EXPENSES: "/api/v1/finance/expenses",
    RECEIPTS: "/api/v1/finance/receipts",
    BUDGETS: "/api/v1/finance/budgets",
    RECONCILIATION_FLOW: "/api/v1/finance/reconciliation-flow",
    BANK_STATEMENTS: "/api/v1/finance/reconciliation/bank-statements",
    BANK_STATEMENTS_IMPORT: "/api/v1/finance/reconciliation/bank-statements/import",
    BANK_STATEMENT_APPROVE: (id: string) =>
      `/api/v1/finance/reconciliation/bank-statements/${id}/approve`,
    BANK_STATEMENT_REJECT: (id: string) =>
      `/api/v1/finance/reconciliation/bank-statements/${id}/reject`,
    VAULT_BALANCES: "/api/v1/finance/vault-balances",
    VAULT_TRANSFERS: "/api/v1/finance/vault-transfers",
    PAYMENTS_CASH: "/api/v1/finance/payments/cash",
    MPESA_CALLBACK: "/api/v1/finance/mpesa/callback",
    // Accounts-payable approval queue (maker-checker)
    PAYABLES_QUEUE: "/api/v1/finance/payables/queue",
    PAYABLES: "/api/v1/finance/payables",
    PAYABLE_APPROVE: (id: string) => `/api/v1/finance/payables/${id}/approve`,
    PAYABLE_REJECT: (id: string) => `/api/v1/finance/payables/${id}/reject`,
    PAYABLE_SCHEDULE: (id: string) => `/api/v1/finance/payables/${id}/schedule`,
  },

  // CRM
  CRM: {
    CUSTOMERS: "/api/v1/crm/customers",
    CUSTOMER: (id: string) => `/api/v1/crm/customers/${id}`,
  },

  // Health (unauthenticated; not under /api/v1)
  HEALTH: {
    READY: "/health/ready",
  },

  // Intelligence
  INTELLIGENCE: {
    INSIGHTS: "/api/v1/intelligence/ai-insights",
    ACTIONS: "/api/v1/intelligence/ai-actions",
    // Cheap GET feeds over persisted orchestration runs (dashboard widgets).
    INSIGHTS_FEED: "/api/v1/intelligence/insights",
    ACTIONS_FEED: "/api/v1/intelligence/actions",
    NOTIFICATIONS: "/api/v1/intelligence/notifications",
    AGENTS: "/api/v1/intelligence/agents",
    INTENT: "/api/v1/intelligence/intent",
    RECEIPT_SCAN: "/api/v1/intelligence/receipts/scan",
    CONVERSATION: "/api/v1/intelligence/conversation",
    CONVERSATION_STATUS: (sessionId: string) =>
      `/api/v1/intelligence/conversation/${sessionId}/status`,
    GENUI_ERROR: "/api/v1/intelligence/genui/error",
  },

  // Alerts (agent-raised finance/compliance alerts)
  ALERTS: {
    ROOT: "/api/v1/alerts",
    RESOLVED: "/api/v1/alerts/resolved",
    KPIS: "/api/v1/alerts/kpis",
    RESOLVE: (id: string) => `/api/v1/alerts/${id}/resolve`,
  },

  // Audit (append-only system-activity trail; managers+)
  AUDIT: {
    ROOT: "/api/v1/audit",
    KPIS: "/api/v1/audit/kpis",
    ENTRY: (id: string) => `/api/v1/audit/${id}`,
  },
} as const;