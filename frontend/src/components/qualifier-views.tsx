import Link from "next/link";

import { formatDateTime } from "@/lib/format";
import { decisionLabel, matchedText, outcomeText } from "@/lib/qualifier";

/**
 * What the Qualifier concluded, in plain words. Every text here was written by a model, so it is
 * shown as plain text only (React escapes it): never as markup, never as a link.
 */
type Shown = {
  decision: string;
  matched_steps: number[];
  reasons: string[];
  missing: string[];
};

export function AssessmentBody({ item }: { item: Shown }) {
  return (
    <>
      <p className="text-sm font-semibold text-slate-900">
        {decisionLabel(item.decision)}
        <span className="font-normal text-slate-600">
          {" "}
          - {matchedText(item.matched_steps)}
        </span>
      </p>
      {item.reasons.length > 0 && (
        <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-slate-700">
          {item.reasons.map((reason, index) => (
            <li key={index} className="whitespace-pre-line break-words">
              {reason}
            </li>
          ))}
        </ul>
      )}
      {item.missing.length > 0 && (
        <p className="mt-2 text-sm text-slate-700">
          Missing:{" "}
          <span className="break-words">{item.missing.join("; ")}</span>
        </p>
      )}
    </>
  );
}

export type HistoryItem = Shown & {
  id: string;
  outcome: string;
  procedure_version: number;
  proposal_link: string | null;
  created_at: string;
  blocked_message?: string | null;
};

export function AssessmentHistory({ items }: { items: HistoryItem[] }) {
  if (items.length === 0)
    return (
      <p className="text-sm text-slate-600">
        This lead has not been assessed yet.
      </p>
    );
  return (
    <ol className="space-y-4">
      {items.map((item, index) => (
        <li
          key={item.id}
          className={index === 0 ? "" : "border-t border-slate-100 pt-4"}
        >
          <AssessmentBody item={item} />
          <p className="mt-2 text-xs text-slate-500">
            {outcomeText(item.outcome)}
            {item.proposal_link && (
              <>
                {" "}
                <Link
                  href={item.proposal_link}
                  className="font-medium text-slate-700 underline"
                >
                  Open the proposal
                </Link>
              </>
            )}
            {" · "}procedure version {item.procedure_version} ·{" "}
            <time dateTime={item.created_at}>
              {formatDateTime(item.created_at)}
            </time>
          </p>
        </li>
      ))}
    </ol>
  );
}
