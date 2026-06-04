// ─── Domain type barrel ────────────────────────────────────────────────────────
// All types below are now derived from the auto-generated OpenAPI schema.
// Run `npm run sync-types` to regenerate src/lib/api/generated/schema.d.ts
// whenever the FastAPI Pydantic models change.
//
// MIGRATION NOTES (from hand-written interfaces → generated aliases):
//
//   • Decimal fields (amount, subtotal, tax, …) are now `number | string`
//     instead of plain `string`.  Pydantic v2 serialises Decimal with
//     anyOf: [number, string] in its OpenAPI JSON schema.
//     Normalise at the call-site: Number(invoice.subtotal).toFixed(2)
//
//   • Invoice gains `amount_paid`, `balance_due`, `notes` — fields that were
//     always present in the API response but absent from the old manual type.
//     TypeScript will now surface any component that ignores these fields.
//
//   • InvoiceStatus gains `"partially_paid"` — it was missing from the old
//     manual union type and caused silent exhaustiveness gaps in switch statements.
//
//   • Customer and LedgerEntry gain `preferred_locale` and `customer_id`
//     respectively, which were likewise absent from the old manual interfaces.
//
// User is kept in @/types/auth because it carries the normalised (UPPERCASE)
// role used by the auth context after JWT decoding.  For raw API responses
// where the role is lowercase use ApiUser from @/types/api.

export type { User } from "@/types/auth";

export type {
  ApiCustomer      as Customer,
  ApiInvoice       as Invoice,
  ApiBudget        as Budget,
  ApiLedgerEntry   as LedgerEntry,
} from "@/types/api";
