export interface User {
  id: string;
  email: string;
  full_name: string;
  role: "admin" | "manager" | "accountant" | "viewer";
  is_active: boolean;
  created_at: string;
}

export interface Customer {
  id: string;
  name: string;
  email: string;
  phone: string | null;
  customer_type: "individual" | "business";
  status: "active" | "inactive" | "prospect" | "churned";
  created_at: string;
}

export interface Invoice {
  id: string;
  customer_id: string;
  invoice_number: string;
  status: "draft" | "sent" | "paid" | "overdue" | "cancelled";
  subtotal: string;
  tax: string;
  total: string;
  currency: string;
  due_date: string | null;
  paid_at: string | null;
  created_at: string;
}

export interface Budget {
  id: string;
  name: string;
  category: string;
  amount: string;
  spent: string;
  currency: string;
  period_start: string;
  period_end: string;
  created_at: string;
}

export interface LedgerEntry {
  id: string;
  account_id: string;
  transaction_type: "debit" | "credit";
  amount: string;
  currency: string;
  description: string | null;
  reference: string | null;
  created_at: string;
}
