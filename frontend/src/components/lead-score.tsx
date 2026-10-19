import { Card, cx } from "@/components/ui";
import type { LeadScore } from "@/lib/api-types";

const STYLE = {
  hot: "bg-red-50 text-red-700 ring-red-200",
  warm: "bg-amber-50 text-amber-800 ring-amber-200",
  cold: "bg-sky-50 text-sky-800 ring-sky-200",
} as const;
const LABEL = { hot: "Hot", warm: "Warm", cold: "Cold" } as const;

/** "Hot · 82" - the lead score and its band. */
export function ScoreBadge({
  score,
  priority,
}: {
  score?: number | null;
  priority?: "hot" | "warm" | "cold" | null;
}) {
  if (score === null || score === undefined || !priority)
    return <span className="text-slate-400">—</span>;
  return (
    <span
      className={cx(
        "inline-flex rounded-full px-2 py-0.5 text-xs font-semibold ring-1 ring-inset",
        STYLE[priority],
      )}
      title={`Lead score ${score} of 100`}
    >
      {LABEL[priority]} · {score}
    </span>
  );
}

/** The score with every factor that added or removed points. */
export function LeadScoreCard({ score }: { score: LeadScore }) {
  return (
    <Card>
      <div className="flex items-center justify-between gap-3 border-b border-slate-200 px-5 py-4">
        <h2 className="text-base font-semibold text-slate-900">Lead score</h2>
        <ScoreBadge score={score.score} priority={score.priority} />
      </div>
      <ul className="space-y-1 px-5 py-4 text-sm">
        {score.factors.length === 0 && (
          <li className="text-slate-600">
            No information yet to score this lead.
          </li>
        )}
        {score.factors.map((f) => (
          <li key={f.label} className="flex justify-between gap-3">
            <span className="text-slate-700">{f.label}</span>
            <span
              className={cx(
                "font-medium",
                f.points < 0 ? "text-red-700" : "text-emerald-700",
              )}
            >
              {f.points > 0 ? `+${f.points}` : f.points}
            </span>
          </li>
        ))}
      </ul>
      <p className="border-t border-slate-100 px-5 py-2 text-xs text-slate-500">
        Hot 70+, warm 40–69, cold under 40. Calls, e-mails, meetings and notes
        in the last 14 days add points; none for over 30 days removes some.
      </p>
    </Card>
  );
}
