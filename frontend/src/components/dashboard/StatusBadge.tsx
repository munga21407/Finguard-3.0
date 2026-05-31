type StatusVariant = "paid" | "sent" | "overdue" | "draft" | "processing" | "cleared" | "active" | "warning";

const variantStyles: Record<StatusVariant, string> = {
  paid:       "bg-[#dcfce7] text-[#166534]",
  cleared:    "bg-[#dcfce7] text-[#166534]",
  sent:       "bg-[#dbeafe] text-[#1e40af]",
  active:     "bg-[#dcfce7] text-[#166534]",
  overdue:    "bg-lf-error-container text-lf-on-error-container",
  warning:    "bg-lf-error-container text-lf-on-error-container",
  draft:      "bg-lf-surface-variant text-lf-on-surface-variant",
  processing: "bg-lf-secondary-fixed/50 text-lf-secondary",
};

interface StatusBadgeProps {
  status: StatusVariant;
  label?: string;
}

export function StatusBadge({ status, label }: StatusBadgeProps) {
  const displayLabel = label ?? status.charAt(0).toUpperCase() + status.slice(1);
  return (
    <span className={`inline-flex items-center px-3 py-1 rounded-full text-xs font-bold ${variantStyles[status]}`}>
      {displayLabel}
    </span>
  );
}
