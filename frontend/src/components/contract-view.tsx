import { cx } from "@/components/ui";
import type { ContractStatus } from "@/lib/api-types";
import {
  CONTRACT_STATUS_LABELS,
  CONTRACT_STATUS_STYLE,
  END_HINT_STYLE,
  endHint,
} from "@/lib/contracts";

export function ContractStatusBadge({ status }: { status: ContractStatus }) {
  return (
    <span
      className={cx(
        "rounded-full px-2.5 py-0.5 text-xs font-medium",
        CONTRACT_STATUS_STYLE[status],
      )}
    >
      {CONTRACT_STATUS_LABELS[status]}
    </span>
  );
}

/** "Ends in 20 days" - only for active contracts, coloured by how close the end is. */
export function EndHint({
  status,
  daysToEnd,
}: {
  status: ContractStatus;
  daysToEnd: number | null;
}) {
  const hint = endHint({ status, days_to_end: daysToEnd });
  if (hint.tone === "none") return null;
  return (
    <span className={cx("text-xs", END_HINT_STYLE[hint.tone])}>
      {hint.text}
    </span>
  );
}
