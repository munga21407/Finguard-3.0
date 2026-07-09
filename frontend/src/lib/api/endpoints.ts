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
    REPORTS: "/api/v1/finance/reports",
    REPORT: (type: string) => `/api/v1/finance/reports/${type}`,
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

  // Inventory
  INVENTORY: {
    PRODUCTS: "/api/v1/inventory/products",
    PRODUCT: (id: string) => `/api/v1/inventory/products/${id}`,
    STOCK: (id: string) => `/api/v1/inventory/products/${id}/stock`,
    MOVEMENTS: (id: string) => `/api/v1/inventory/products/${id}/movements`,
    ADJUST: (id: string) => `/api/v1/inventory/products/${id}/adjust`,
    PRODUCT_MOVEMENTS: (id: string) => `/api/v1/inventory/products/${id}/movements`,
    PRODUCT_ADJUST: (id: string) => `/api/v1/inventory/products/${id}/adjust`,
    LEVELS: "/api/v1/inventory/levels",
    VALUATION: "/api/v1/inventory/reports/valuation",
    LOW_STOCK: "/api/v1/inventory/reports/low-stock",
    VALUATION_REPORT: "/api/v1/inventory/reports/valuation",
    LOW_STOCK_REPORT: "/api/v1/inventory/reports/low-stock",
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
    // Human-in-the-loop approval queue for value-changing agent actions.
    PROPOSALS: "/api/v1/intelligence/proposals",
    PROPOSAL_APPROVE: (id: string) => `/api/v1/intelligence/proposals/${id}/approve`,
    PROPOSAL_REJECT: (id: string) => `/api/v1/intelligence/proposals/${id}/reject`,
    // Admin: upload a KRA regulatory doc into the Tax RAG knowledge base.
    KB_INGEST: "/api/v1/intelligence/admin/knowledge-base/ingest",
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
