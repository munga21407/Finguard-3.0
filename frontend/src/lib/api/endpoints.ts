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
    BUDGETS: "/api/v1/finance/budgets",
    PAYMENTS_CASH: "/api/v1/finance/payments/cash",
    MPESA_CALLBACK: "/api/v1/finance/mpesa/callback",
  },

  // CRM
  CRM: {
    CUSTOMERS: "/api/v1/crm/customers",
    CUSTOMER: (id: string) => `/api/v1/crm/customers/${id}`,
  },

  // Intelligence
  INTELLIGENCE: {
    INSIGHTS: "/api/v1/intelligence/ai-insights",
    ACTIONS: "/api/v1/intelligence/ai-actions",
    INTENT: "/api/v1/intelligence/intent",
    CONVERSATION: "/api/v1/intelligence/conversation",
    CONVERSATION_STATUS: (sessionId: string) =>
      `/api/v1/intelligence/conversation/${sessionId}/status`,
  },
} as const;