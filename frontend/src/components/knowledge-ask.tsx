"use client";

import { useActionState } from "react";

import { ErrorAlert, buttonClass } from "@/components/ui";
import type { KnowledgeAnswerResponse } from "@/lib/api-types";
import {
  initialAskState,
  initialFeedbackState,
  type AskState,
  type FeedbackState,
} from "@/lib/knowledge";

const field =
  "mt-1 block w-full rounded-md border-0 bg-white px-3 py-2 text-sm text-slate-900 ring-1 ring-inset ring-slate-300 focus:ring-2 focus:ring-brand-600";

/** Question box: answers in place, with the exact cited passages underneath. */
export function KnowledgeAsk({
  action,
  feedbackAction,
}: {
  action: (state: AskState, formData: FormData) => Promise<AskState>;
  feedbackAction?: (state: FeedbackState, formData: FormData) => Promise<FeedbackState>;
}) {
  const [state, formAction, pending] = useActionState(action, initialAskState);

  return (
    <div className="space-y-5">
      <form action={formAction} className="space-y-3">
        {state.error && (
          <ErrorAlert title="The question could not be answered" error={state.error} />
        )}
        <div>
          <label htmlFor="ask-question" className="text-sm font-medium text-slate-700">
            Your question
          </label>
          <textarea
            id="ask-question"
            name="question"
            rows={3}
            maxLength={500}
            required
            defaultValue={state.question}
            placeholder="e.g. How long do customers have to return a damaged item?"
            className={field}
          />
          {state.fieldError && (
            <p className="mt-1 text-sm text-red-700">{state.fieldError}</p>
          )}
          <p className="mt-1 text-xs text-slate-500">
            Answers come only from indexed documents and cite their passages.
          </p>
        </div>
        <button type="submit" disabled={pending} className={buttonClass("primary")}>
          {pending ? "Searching and answering…" : "Ask the knowledge base"}
        </button>
      </form>
      {state.answer && <AnswerView answer={state.answer} feedbackAction={feedbackAction} />}
    </div>
  );
}

function AnswerView({
  answer,
  feedbackAction,
}: {
  answer: KnowledgeAnswerResponse;
  feedbackAction?: (state: FeedbackState, formData: FormData) => Promise<FeedbackState>;
}) {
  return (
    <div className="space-y-4">
      <div
        role="status"
        className={
          answer.enough
            ? "rounded-md border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-950"
            : "rounded-md border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900"
        }
      >
        <p className="whitespace-pre-line">{answer.answer}</p>
        {answer.grounded && (
          <p className="mt-2 text-xs text-emerald-800">
            Grounded in {answer.sources.length} source
            {answer.sources.length === 1 ? "" : "s"}; citations{" "}
            {answer.citations.map((n) => `[${n}]`).join(", ")}
          </p>
        )}
        {!answer.enough && (
          <p className="mt-2 text-xs">
            Nothing in the knowledge base was close enough; try different words or ask a colleague.
          </p>
        )}
      </div>
      {feedbackAction && answer.query_id && (
        <AnswerFeedback queryId={answer.query_id} action={feedbackAction} />
      )}
      {answer.sources.length > 0 && (
        <div>
          <h3 className="text-sm font-semibold text-slate-900">Sources used</h3>
          <ol className="mt-2 space-y-3">
            {answer.sources.map((source, index) => (
              <li key={source.chunk_id} className="rounded-md bg-slate-50 p-3 text-sm ring-1 ring-slate-200">
                <p className="font-medium text-slate-900">
                  [{index + 1}] {source.document_title}
                  {source.heading_path ? ` - ${source.heading_path}` : ""}
                  {source.page_from !== null && (
                    <span className="ml-1 font-normal text-slate-500">p. {source.page_from}</span>
                  )}
                </p>
                <p className="mt-1 whitespace-pre-line text-slate-600">
                  {source.text.length > 400 ? source.text.slice(0, 400) + "…" : source.text}
                </p>
              </li>
            ))}
          </ol>
        </div>
      )}
    </div>
  );
}

function AnswerFeedback({
  queryId,
  action,
}: {
  queryId: string;
  action: (state: FeedbackState, formData: FormData) => Promise<FeedbackState>;
}) {
  const [state, formAction, pending] = useActionState(action, initialFeedbackState);

  if (state.done) {
    return (
      <p role="status" className="text-xs text-slate-600">
        Thanks — your feedback helps improve the knowledge base.
      </p>
    );
  }
  return (
    <form action={formAction} className="flex flex-wrap items-center gap-2 text-xs">
      <input type="hidden" name="query_id" value={queryId} />
      {state.error && <ErrorAlert title="Feedback could not be saved" error={state.error} />}
      <span className="text-slate-600">Was this helpful?</span>
      <button type="submit" name="helpful" value="true" disabled={pending} className="rounded-md bg-white px-2.5 py-1 ring-1 ring-inset ring-slate-300 hover:bg-slate-50">
        Helpful
      </button>
      <button type="submit" name="helpful" value="false" disabled={pending} className="rounded-md bg-white px-2.5 py-1 ring-1 ring-inset ring-slate-300 hover:bg-slate-50">
        Not helpful
      </button>
    </form>
  );
}
