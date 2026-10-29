import Link from "next/link";
import type { ReactNode } from "react";

import { Card, cx } from "@/components/ui";
import type {
  AgentAction,
  AgentActionStatus,
  AssistantProposal,
  Me,
} from "@/lib/api-types";
import {
  APPROVAL_STATUS_LABELS,
  describeChange,
  fieldLabel,
} from "@/lib/approvals";
import { formatDateTime } from "@/lib/format";

const BADGE: Record<AgentActionStatus, string> = {
  pending: "bg-amber-50 text-amber-800 ring-amber-200",
  approved: "bg-emerald-50 text-emerald-800 ring-emerald-200",
  rejected: "bg-slate-100 text-slate-700 ring-slate-300",
  expired: "bg-slate-100 text-slate-600 ring-slate-300",
  failed: "bg-red-50 text-red-700 ring-red-200",
};

/** The status as a word (never colour alone). */
export function ApprovalStatusBadge({ status }: { status: AgentActionStatus }) {
  return (
    <span
      className={cx(
        "inline-flex rounded-full px-2 py-0.5 text-xs font-semibold ring-1 ring-inset",
        BADGE[status],
      )}
    >
      {APPROVAL_STATUS_LABELS[status]}
    </span>
  );
}

const AGENT_LABELS: Record<string, string> = {
  staff_assistant: "the staff assistant",
};

/**
 * One AI proposal: what it would do, on which record, why, who asked, and how it ended. All
 * texts come from a model or a person, so they are shown as plain text (React escapes them).
 * `decision` is the slot for the Approve / Reject buttons (the page decides whether to show them).
 */
export function ApprovalCard({
  action,
  people,
  me,
  decision,
  headingLevel = 3,
}: {
  action: AgentAction;
  people: Record<string, string>;
  me: Pick<Me, "user_id">;
  decision?: ReactNode;
  headingLevel?: 2 | 3;
}) {
  const Heading = headingLevel === 2 ? "h2" : "h3";
  const nameOf = (id: string | null) =>
    id === null
      ? ""
      : id === me.user_id
        ? "you"
        : (people[id] ?? "a former colleague");
  const headingId = `approval-${action.id}`;
  return (
    <article aria-labelledby={headingId}>
      <Card className="p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <Heading
            id={headingId}
            className="min-w-0 text-base font-semibold text-slate-900"
          >
            {action.description}
          </Heading>
          <ApprovalStatusBadge status={action.status} />
        </div>
        <dl className="mt-3 space-y-2 text-sm">
          <div>
            <dt className="inline text-slate-500">About: </dt>
            <dd className="inline text-slate-900">
              {action.target_label ? (
                <Link
                  href={action.target_link}
                  className="font-medium text-brand-700 hover:underline"
                >
                  {action.target_label}
                </Link>
              ) : (
                "A record you can't see"
              )}
            </dd>
          </div>
          <div>
            <dt className="text-slate-500">Why it is proposed</dt>
            <dd className="whitespace-pre-line break-words text-slate-900">
              {action.reason}
            </dd>
          </div>
        </dl>
        <p className="mt-3 text-xs text-slate-500">
          Asked by {nameOf(action.requested_by_user_id)} through{" "}
          {AGENT_LABELS[action.agent] ?? "an AI feature"} ·{" "}
          <time dateTime={action.created_at}>
            {formatDateTime(action.created_at)}
          </time>
          {action.status === "pending" && (
            <>
              {" "}
              · expires{" "}
              <time dateTime={action.expires_at}>
                {formatDateTime(action.expires_at)}
              </time>
            </>
          )}
        </p>
        {action.changes.length > 0 && (
          <div
            role="group"
            aria-label="Would change"
            className="mt-4 rounded-md border border-slate-200 bg-slate-50 p-3 text-sm text-slate-800"
          >
            <p className="font-semibold">Would change</p>
            <ul className="mt-1 list-disc pl-5">
              {action.changes.map((change) => (
                <li key={change.field} className="break-words">
                  {describeChange(change, nameOf)}
                </li>
              ))}
            </ul>
          </div>
        )}
        {action.outcome && (
          <div
            role="group"
            aria-label="What happened"
            className={cx(
              "mt-4 rounded-md border p-3 text-sm",
              action.outcome.matches_plan === false
                ? "border-red-200 bg-red-50 text-red-800"
                : "border-slate-200 bg-slate-50 text-slate-800",
            )}
          >
            <p className="font-semibold">What happened</p>
            <p className="mt-1">
              {!action.outcome.ran
                ? "It did not run, so nothing was changed."
                : action.outcome.matches_plan === true
                  ? "It ran and matched what was announced."
                  : action.outcome.matches_plan === false
                    ? `It ran, but the result did not match the plan: ${action.outcome.differs.map(fieldLabel).join(", ")}.`
                    : "It ran."}
            </p>
          </div>
        )}
        {action.warnings.length > 0 && (
          <div
            role="group"
            aria-label="Safety check"
            className="mt-4 rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900"
          >
            <p className="font-semibold">Safety check</p>
            <p className="text-xs text-amber-800">
              Check this before you decide:
            </p>
            <ul className="mt-1 list-disc pl-5">
              {action.warnings.map((warning) => (
                <li key={warning.code} className="break-words">
                  {warning.message}
                </li>
              ))}
            </ul>
          </div>
        )}
        {action.status !== "pending" && action.decided_at && (
          <div className="mt-3 border-t border-slate-100 pt-3 text-sm text-slate-700">
            <p>
              {action.status === "expired"
                ? "Nobody decided in time."
                : `Decided by ${nameOf(action.decided_by_user_id)}`}{" "}
              ·{" "}
              <time dateTime={action.decided_at}>
                {formatDateTime(action.decided_at)}
              </time>
            </p>
            {action.decision_note && (
              <p className="mt-1 whitespace-pre-line break-words">
                Note: {action.decision_note}
              </p>
            )}
            {action.result && (
              <p className="mt-1 whitespace-pre-line break-words text-slate-600">
                Result: {action.result}
              </p>
            )}
          </div>
        )}
        {decision && (
          <div className="mt-4 flex flex-wrap justify-end gap-3 border-t border-slate-100 pt-4">
            {decision}
          </div>
        )}
      </Card>
    </article>
  );
}

/** On a lead, account or contact page: what the AI proposed for this record and is waiting. */
export function RecordProposalsList({ items }: { items: AgentAction[] }) {
  const waiting = items.filter((a) => a.status === "pending");
  if (waiting.length === 0) return null;
  return (
    <Card>
      <section
        aria-labelledby="record-proposals-heading"
        aria-label="AI proposals"
      >
        <h2
          id="record-proposals-heading"
          className="border-b border-slate-200 px-5 py-4 text-base font-semibold text-slate-900"
        >
          AI proposals
        </h2>
        <ul className="divide-y divide-slate-100">
          {waiting.map((a) => (
            <li key={a.id} className="px-5 py-3 text-sm">
              <Link
                href={`/approvals/${a.id}`}
                className="font-medium text-brand-700 hover:underline"
              >
                {a.description}
              </Link>
              <p className="mt-0.5 text-xs text-slate-500">
                Waiting for approval · expires{" "}
                <time dateTime={a.expires_at}>
                  {formatDateTime(a.expires_at)}
                </time>
              </p>
            </li>
          ))}
        </ul>
      </section>
    </Card>
  );
}

/** In the assistant's answer: what it proposed. Nothing has happened yet - a manager decides. */
export function AssistantProposals({
  proposals,
}: {
  proposals: AssistantProposal[];
}) {
  if (proposals.length === 0) return null;
  return (
    <section
      aria-label="Waiting for approval"
      className="mt-4 rounded-md border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900"
    >
      <h3 className="font-semibold">Waiting for approval</h3>
      <p className="mt-1">
        Nothing has changed yet. A manager decides on{" "}
        {proposals.length === 1 ? "this proposal" : "these proposals"}.
      </p>
      <ul className="mt-2 list-disc space-y-1 pl-5">
        {proposals.map((p) => (
          <li key={p.id}>
            <Link
              href={p.link}
              className="font-medium text-brand-700 hover:underline"
            >
              {p.description}
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}
