import { cx } from "@/components/ui";
import { LEVEL_LABELS, LEVEL_STYLES, type RiskLevel } from "@/lib/deal-risk";

/** A forecast level written out in words (never colour alone). Safe in client components. */
export function RiskBadge({ level }: { level: RiskLevel }) {
  return (
    <span
      className={cx(
        "rounded px-2 py-0.5 text-xs font-medium",
        LEVEL_STYLES[level],
      )}
      data-testid="risk-badge"
    >
      {LEVEL_LABELS[level]}
    </span>
  );
}
