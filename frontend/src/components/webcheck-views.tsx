import { cx } from "@/components/ui";
import type {
  WebCheckSource,
  WebEvidence,
  WebEvidenceVerdict,
} from "@/lib/api-types";
import { formatDate, formatDateTime } from "@/lib/format";
import {
  cleanedNotes,
  errorText,
  statusLabel,
  verdictLabel,
} from "@/lib/webcheck";

const BADGE: Record<WebEvidenceVerdict, string> = {
  found: "bg-emerald-50 text-emerald-800 ring-emerald-200",
  not_found: "bg-slate-100 text-slate-700 ring-slate-300",
  unclear: "bg-amber-50 text-amber-800 ring-amber-200",
  error: "bg-red-50 text-red-700 ring-red-200",
};

/** The verdict as a word (never colour alone). */
export function VerdictBadge({ verdict }: { verdict: WebEvidenceVerdict }) {
  return (
    <span
      className={cx(
        "inline-flex rounded-full px-2 py-0.5 text-xs font-semibold ring-1 ring-inset",
        BADGE[verdict],
      )}
    >
      {verdictLabel(verdict)}
    </span>
  );
}

/**
 * The evidence of the web checks of one lead or account (ADR 0019), newest first. Everything
 * here came from a page somebody else wrote, so it is shown as plain text (React escapes it);
 * the server already cleaned it, and a note says when it did. The page itself is not linked.
 */
export function WebEvidenceList({
  items,
  sources,
}: {
  items: WebEvidence[];
  sources: WebCheckSource[];
}) {
  if (items.length === 0)
    return (
      <p className="text-sm text-slate-600">No web check has been made yet.</p>
    );
  const titleOf = (key: string) =>
    sources.find((source) => source.key === key)?.title ?? key;
  return (
    <ul className="divide-y divide-slate-100">
      {items.map((item) => {
        const notes = cleanedNotes(item.cleaned);
        return (
          <li key={item.id} className="space-y-1 py-3 text-sm">
            <div className="flex flex-wrap items-center gap-2">
              <VerdictBadge verdict={item.verdict} />
              {item.registered_name && (
                <span className="font-medium text-slate-900">
                  {item.registered_name}
                </span>
              )}
              {item.status && (
                <span className="text-slate-700">
                  {statusLabel(item.status)}
                </span>
              )}
            </div>
            {item.valid_until && (
              <p className="text-slate-700">
                Valid until {formatDate(item.valid_until)}
              </p>
            )}
            {item.verdict === "error" && (
              <p className="text-slate-700">{errorText(item.error_code)}</p>
            )}
            <p className="text-xs text-slate-500">
              {titleOf(item.source_key)} · looked up{" "}
              <span className="font-mono">{item.query}</span> ·{" "}
              <time dateTime={item.created_at}>
                {formatDateTime(item.created_at)}
              </time>
            </p>
            {item.excerpt && (
              <details className="text-xs text-slate-600">
                <summary className="cursor-pointer">What the page said</summary>
                <p className="mt-1 whitespace-pre-line break-words">
                  {item.excerpt}
                </p>
              </details>
            )}
            {notes.length > 0 && (
              <p className="text-xs text-amber-800">
                Some text from the page was cleaned: {notes.join("; ")}.
              </p>
            )}
          </li>
        );
      })}
    </ul>
  );
}
