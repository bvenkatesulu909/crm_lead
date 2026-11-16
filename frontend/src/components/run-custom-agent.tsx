"use client";

import Link from "next/link";
import { useActionState } from "react";

import { ErrorAlert, buttonClass } from "@/components/ui";
import {
  initialRunState,
  outcomeText,
  type RunState,
} from "@/lib/custom-agents";

type Action = (state: RunState) => Promise<RunState>;

/**
 * "Run <agent>" on one record (ADR 0034). The agent only suggests: the result is at most one
 * proposal in the approval queue, and nothing changes until a different person approves it. The
 * API reports when the agent is switched off, over budget or over a limit; the words come from
 * the server action.
 */
export function RunCustomAgentButton({
  name,
  purpose,
  action,
}: {
  name: string;
  purpose: string;
  action: Action;
}) {
  const [state, formAction, pending] = useActionState(action, initialRunState);
  const result = state.result;
  return (
    <form action={formAction} className="space-y-2" aria-label={`Run ${name}`}>
      {state.error && (
        <ErrorAlert title={`${name} could not run`} error={state.error} />
      )}
      <div className="flex flex-wrap items-center gap-3">
        <button
          type="submit"
          disabled={pending}
          className={buttonClass("secondary")}
        >
          {pending ? "Working…" : `Run ${name}`}
        </button>
        <span className="text-sm text-slate-600">{purpose}</span>
      </div>
      {result && (
        <p role="status" className="text-sm text-slate-800">
          {outcomeText(result.outcome)}{" "}
          {result.proposal_link && (
            <Link
              href={result.proposal_link}
              className="font-medium text-indigo-700 underline"
            >
              Open the suggestion
            </Link>
          )}
          {result.blocked_message && (
            <span className="block text-slate-600">
              {result.blocked_message}
            </span>
          )}
        </p>
      )}
    </form>
  );
}
