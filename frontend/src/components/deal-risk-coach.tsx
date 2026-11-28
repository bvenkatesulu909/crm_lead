"use client";

import Link from "next/link";
import { useActionState } from "react";

import { ErrorAlert, buttonClass } from "@/components/ui";
import {
  coachProposalLink,
  initialCoachState,
  type CoachState,
  type DealRiskCoach,
} from "@/lib/deal-risk";

type Action = (state: CoachState) => Promise<CoachState>;

/** The coach's answer as plain text (what a model wrote is never HTML here). */
export function DealRiskCoachView({ result }: { result: DealRiskCoach }) {
  return (
    <div
      className="space-y-3 rounded-md bg-slate-50 p-3"
      data-testid="coach-advice"
    >
      <p className="text-xs font-medium uppercase tracking-wide text-slate-500">
        AI coach
      </p>
      {result.advice.length === 0 ? (
        <p className="text-sm text-slate-700">
          The coach had no advice for this deal.
        </p>
      ) : (
        <ul className="list-disc space-y-1 pl-5 text-sm text-slate-800">
          {result.advice.map((line, i) => (
            <li key={i}>{line.text}</li>
          ))}
        </ul>
      )}
      {result.proposals.length > 0 && (
        <div>
          <p className="text-sm font-medium text-slate-900">
            Suggested tasks (waiting for approval)
          </p>
          <ul className="mt-1 space-y-1">
            {result.proposals.map((p, i) => {
              const href = coachProposalLink(p.link);
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
      {result.blocked_messages.length > 0 && (
        <p className="text-xs text-slate-600">
          The safety check stopped {result.blocked_messages.length} suggested
          task{result.blocked_messages.length === 1 ? "" : "s"}.
        </p>
      )}
      {result.cleaned && (
        <p className="text-xs text-slate-600">
          Some of the coach&apos;s text was cleaned (links or markup removed).
        </p>
      )}
      <p className="text-xs text-slate-500">{result.note}</p>
    </div>
  );
}

/**
 * "Ask the AI coach": optional advice on the forecast (ADR 0037, DR5). The coach sees only the
 * forecast, never changes it, and any task it suggests waits for a different person to approve.
 * The API says when it is switched off, over budget or over its limit.
 */
export function DealRiskCoachButton({ action }: { action: Action }) {
  const [state, formAction, pending] = useActionState(
    action,
    initialCoachState,
  );
  return (
    <div className="space-y-3">
      <form action={formAction}>
        <button
          type="submit"
          disabled={pending}
          className={buttonClass("secondary")}
        >
          {pending ? "Asking the coach…" : "Ask the AI coach"}
        </button>
      </form>
      {state.error && (
        <ErrorAlert
          title="The coach could not help this time"
          error={state.error}
        />
      )}
      {state.result && <DealRiskCoachView result={state.result} />}
    </div>
  );
}
