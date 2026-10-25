import { cx } from "@/components/ui";
import type { EmailStatus } from "@/lib/api-types";
import { EMAIL_STATUS_LABELS } from "@/lib/communications";

const STATUS_STYLES: Record<EmailStatus, string> = {
  queued: "bg-amber-50 text-amber-800 ring-amber-200",
  sent: "bg-emerald-50 text-emerald-800 ring-emerald-200",
  failed: "bg-red-50 text-red-800 ring-red-200",
  logged: "bg-sky-50 text-sky-800 ring-sky-200",
};

/** "Sending", "Sent", "Not delivered" or "Received". */
export function EmailStatusBadge({ status }: { status: EmailStatus }) {
  return (
    <span
      className={cx(
        "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset",
        STATUS_STYLES[status],
      )}
    >
      {EMAIL_STATUS_LABELS[status]}
    </span>
  );
}
