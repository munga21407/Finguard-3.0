// ─── GenUI icon resolver ────────────────────────────────────────────────────
// GenUI props arrive as JSON from an LLM tool call, so icons are named by string
// (e.g. "trending-up", "Wallet"). This maps a curated set of lucide icons by a
// normalised key (lowercase, alphanumerics only) so "TrendingUp", "trending_up"
// and "trending-up" all resolve. Curated (not the full lucide set) to keep the
// lazily-loaded GenUI bundles small.

import {
  Activity,
  AlertTriangle,
  ArrowDownRight,
  ArrowUpRight,
  Banknote,
  BarChart3,
  Building2,
  CheckCircle2,
  Clock,
  CreditCard,
  DollarSign,
  Landmark,
  LineChart,
  Package,
  PiggyBank,
  Receipt,
  ShieldCheck,
  ShoppingCart,
  TrendingDown,
  TrendingUp,
  Users,
  Wallet,
  type LucideIcon,
} from "lucide-react";

const MAP: Record<string, LucideIcon> = {
  activity: Activity,
  alerttriangle: AlertTriangle,
  arrowdownright: ArrowDownRight,
  arrowupright: ArrowUpRight,
  banknote: Banknote,
  barchart: BarChart3,
  barchart3: BarChart3,
  building: Building2,
  building2: Building2,
  checkcircle: CheckCircle2,
  checkcircle2: CheckCircle2,
  clock: Clock,
  creditcard: CreditCard,
  dollarsign: DollarSign,
  landmark: Landmark,
  linechart: LineChart,
  package: Package,
  piggybank: PiggyBank,
  receipt: Receipt,
  shieldcheck: ShieldCheck,
  shoppingcart: ShoppingCart,
  trendingdown: TrendingDown,
  trendingup: TrendingUp,
  users: Users,
  wallet: Wallet,
};

const normalise = (name?: string) => (name ?? "").toLowerCase().replace(/[^a-z0-9]/g, "");

/** Resolve a JSON icon name to a lucide component, falling back to `fallback`. */
export function resolveIcon(name?: string, fallback: LucideIcon = Activity): LucideIcon {
  return MAP[normalise(name)] ?? fallback;
}
