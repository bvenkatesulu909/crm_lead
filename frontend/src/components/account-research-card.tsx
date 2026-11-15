import Link from "next/link";

import { researchAccount } from "@/app/(app)/deal-desk/research-actions";
import { ResearchButton } from "@/components/account-research-button";
import { Card } from "@/components/ui";
import type { Me } from "@/lib/api-types";
import { recordLink, type AccountBrief } from "@/lib/deal-desk";
import { formatDateTime } from "@/lib/format";
import { canResearchAccounts } from "@/lib/permissions";
import { apiFetch } from "@/lib/server/api";

const LINK_LABEL: Record<string, string> = {
  opportunity: "deal",
  contract: "contract",
};

/** One brief as plain text; each sentence links to the deal or contract it names (the account
 * itself is this page). */
export function AccountBriefView({ brief }: { brief: AccountBrief }) {
  return (
    <div className="space-y-3">
      <p className="text-xs text-slate-500">
        Written {formatDateTime(brief.created_at)} from the CRM&apos;s own
        records
      </p>
      <ul className="list-disc space-y-2 pl-5">
        {brief.sentences.map((s, i) => (
          <li key={i} className="text-sm text-slate-800">
            {s.text}
            {s.records.map((r) => {
              const href =
                r.type !== "account" ? recordLink(r.type, r.id) : null;
              return href ? (
                <Link
                  key={r.id}
                  href={href}
                  className="ml-2 text-xs font-medium text-brand-700 hover:underline"
                >
                  Open {LINK_LABEL[r.type]}
                </Link>
              ) : null;
            })}
          </li>
        ))}
      </ul>
      {brief.dropped > 0 && (
        <p className="text-xs text-slate-500">
          {brief.dropped} sentence(s) were left out because they named no
          source.
        </p>
      )}
    </div>
  );
}

/**
 * Account research on an account page (ADR 0024): the newest brief and the "Research this
 * account" button for people with account_research:run. Information only - the page works
 * without it; the API decides again.
 */
export async function AccountResearchCard({
  me,
  accountId,
}: {
  me: Pick<Me, "permissions">;
  accountId: string;
}) {
  const mayAsk = canResearchAccounts(me);
  const briefs = await apiFetch<{ items: AccountBrief[] }>(
    `/account-research/briefs?account_id=${accountId}`,
  ).catch(() => null);
  const newest = briefs?.items[0];
  if (!mayAsk && !newest) return null;
  return (
    <Card
      id="account-research"
      aria-labelledby="account-research-heading"
      className="p-5"
    >
      <h2
        id="account-research-heading"
        className="text-base font-semibold text-slate-900"
      >
        Account research
      </h2>
      <div className="mt-3 space-y-4">
        {newest ? (
          <AccountBriefView brief={newest} />
        ) : (
          <p className="text-sm text-slate-600">
            No brief has been written for this account yet.
          </p>
        )}
        {mayAsk && (
          <ResearchButton action={researchAccount.bind(null, accountId)} />
        )}
      </div>
    </Card>
  );
}
