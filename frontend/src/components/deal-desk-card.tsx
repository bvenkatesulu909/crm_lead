import Link from "next/link";

import { askDealDesk } from "@/app/(app)/deal-desk/actions";
import { AskDealDeskButton } from "@/components/deal-desk-button";
import { Card, cx } from "@/components/ui";
import type { Me } from "@/lib/api-types";
import {
  RECORD_LABELS,
  REVIEWER_LABELS,
  SEVERITY_LABELS,
  proposalLink,
  recordLink,
  type DealDeskFinding,
  type DealDeskReview,
  type DealDeskReviewer,
} from "@/lib/deal-desk";
import { formatDateTime } from "@/lib/format";
import { canRunDealDesk } from "@/lib/permissions";
import { apiFetch } from "@/lib/server/api";

const SEVERITY_STYLES: Record<DealDeskFinding["severity"], string> = {
  act: "bg-red-50 text-red-700",
  watch: "bg-amber-50 text-amber-800",
  info: "bg-slate-100 text-slate-600",
};

const ORDER: DealDeskReviewer[] = ["pricing", "account", "momentum"];

/** The newest review of a deal, as plain text (what a model wrote is never HTML here). */
export function DealDeskReviewView({ review }: { review: DealDeskReview }) {
  const silent = ORDER.filter((r) => review.reviewers[r] === "refused");
  return (
    <div className="space-y-4">
      <p className="text-xs text-slate-500">
        Reviewed {formatDateTime(review.created_at)}
      </p>
      <p className="whitespace-pre-line text-sm text-slate-900">
        {review.brief}
      </p>
      {ORDER.map((reviewer) => {
        const found = review.findings.filter((f) => f.reviewer === reviewer);
        if (found.length === 0) return null;
        return (
          <div key={reviewer}>
            <h3 className="text-sm font-medium text-slate-900">
              {REVIEWER_LABELS[reviewer]}
            </h3>
            <ul className="mt-1 space-y-2">
              {found.map((f, i) => (
                <li key={i} className="text-sm text-slate-700">
                  <span
                    className={cx(
                      "mr-2 rounded px-1.5 py-0.5 text-xs font-medium",
                      SEVERITY_STYLES[f.severity],
                    )}
                  >
                    {SEVERITY_LABELS[f.severity]}
                  </span>
                  {f.text}
                  {f.records.map((r) => {
                    const href = recordLink(r.type, r.id);
                    return href && r.type !== "opportunity" ? (
                      <Link
                        key={r.id}
                        href={href}
                        className="ml-2 text-xs font-medium text-brand-700 hover:underline"
                      >
                        Open {RECORD_LABELS[r.type]}
                      </Link>
                    ) : null;
                  })}
                </li>
              ))}
            </ul>
          </div>
        );
      })}
      {silent.length > 0 && (
        <p className="text-xs text-slate-500">
          No usable answer this time from:{" "}
          {silent.map((r) => REVIEWER_LABELS[r]).join(", ")}.
        </p>
      )}
      {review.proposals.length > 0 && (
        <div>
          <h3 className="text-sm font-medium text-slate-900">
            Suggested tasks (waiting for approval)
          </h3>
          <ul className="mt-1 space-y-1">
            {review.proposals.map((p, i) => {
              const href = proposalLink(p.link);
              return href ? (
                <li key={p.id}>
                  <Link
                    href={href}
                    className="text-sm font-medium text-brand-700 hover:underline"
                  >
                    Suggested task {i + 1}
                  </Link>
                </li>
              ) : null;
            })}
          </ul>
        </div>
      )}
    </div>
  );
}

/**
 * The deal desk on a deal page (ADR 0024): the newest review and the "Review this deal" button.
 * Like the other extra cards it is information - the page works without it. The button is shown to
 * people with deal_desk:run on an open deal (a sales agent: their own deals); the API decides again.
 */
export async function DealDeskCard({
  me,
  opportunity,
}: {
  me: Pick<Me, "permissions" | "user_id">;
  opportunity: { id: string; owner_id: string | null; is_open: boolean };
}) {
  const manager = me.permissions.includes("opportunity:read:all");
  const mayAsk =
    canRunDealDesk(me) &&
    opportunity.is_open &&
    (manager || opportunity.owner_id === me.user_id);
  const reviews = await apiFetch<{ items: DealDeskReview[] }>(
    `/deal-desk/reviews?opportunity_id=${opportunity.id}`,
  ).catch(() => null);
  const newest = reviews?.items[0];
  if (!mayAsk && !newest) return null;
  return (
    <Card id="deal-desk" aria-labelledby="deal-desk-heading" className="p-5">
      <h2
        id="deal-desk-heading"
        className="text-base font-semibold text-slate-900"
      >
        Deal desk
      </h2>
      <div className="mt-3 space-y-4">
        {newest ? (
          <DealDeskReviewView review={newest} />
        ) : (
          <p className="text-sm text-slate-600">
            This deal has not been reviewed yet.
          </p>
        )}
        {mayAsk && (
          <AskDealDeskButton action={askDealDesk.bind(null, opportunity.id)} />
        )}
      </div>
    </Card>
  );
}
