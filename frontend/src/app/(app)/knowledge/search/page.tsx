import type { Metadata } from "next";

import { KnowledgeAsk } from "@/components/knowledge-ask";
import {
  ButtonLink,
  Card,
  EmptyState,
  ErrorAlert,
  Forbidden,
  PageHeader,
  buttonClass,
} from "@/components/ui";
import { ApiError, toErrorInfo } from "@/lib/api-error";
import type { KnowledgeSearchResponse } from "@/lib/api-types";
import { citationLabel, excerpt, matchLabel } from "@/lib/knowledge";
import { canReadKnowledge } from "@/lib/permissions";
import { apiFetch, getMe } from "@/lib/server/api";

import { askKnowledge, submitAnswerFeedback } from "./actions";

export const metadata: Metadata = { title: "Search knowledge" };

const field =
  "mt-1 block w-full rounded-md border-0 bg-white px-3 py-2 text-sm text-slate-900 ring-1 ring-inset ring-slate-300 focus:ring-2 focus:ring-brand-600";

export default async function KnowledgeSearchPage({
  searchParams,
}: PageProps<"/knowledge/search">) {
  const raw = await searchParams;
  const one = (value: string | string[] | undefined) =>
    (Array.isArray(value) ? value[0] : value) ?? "";
  const q = one(raw.q).trim().slice(0, 500);

  const me = await getMe();
  if (!canReadKnowledge(me)) return <Forbidden />;

  let data: KnowledgeSearchResponse | null = null;
  let failure = null;
  if (q) {
    try {
      data = await apiFetch<KnowledgeSearchResponse>(
        `/knowledge/search?q=${encodeURIComponent(q)}&limit=10`,
      );
    } catch (error) {
      if (error instanceof ApiError && error.status === 403) return <Forbidden />;
      failure = toErrorInfo(error);
    }
  }

  return (
    <>
      <PageHeader
        title="Search knowledge"
        description="Find the exact passage behind a policy, then ask a question grounded in those passages."
        actions={
          <ButtonLink href="/knowledge" variant="secondary">
            Manage documents
          </ButtonLink>
        }
      />
      <div className="grid gap-6 lg:grid-cols-2">
        <Card className="p-5">
          <form role="search" aria-label="Search knowledge" className="space-y-3">
            <div>
              <label htmlFor="knowledge-q" className="text-sm font-medium text-slate-700">
                Search passages
              </label>
              <input
                id="knowledge-q"
                name="q"
                type="search"
                defaultValue={q}
                maxLength={500}
                placeholder="e.g. damaged item return"
                className={field}
              />
              <p className="mt-1 text-xs text-slate-500">
                Meaning (embeddings) + keywords, reranked. Search works without the answer model.
              </p>
            </div>
            <button type="submit" className={buttonClass("primary")}>
              Search
            </button>
          </form>

          {failure && (
            <div className="mt-4">
              <ErrorAlert title="Search failed" error={failure} />
            </div>
          )}
          {q && data && (
            <div className="mt-5">
              {data.results.length === 0 ? (
                <EmptyState
                  title="No matching passages"
                  description="Try different words, or upload the policy if it is missing."
                />
              ) : (
                <>
                  <p className="text-sm text-slate-600">
                    {data.results.length} passage{data.results.length === 1 ? "" : "s"} for{" "}
                    <span className="font-medium text-slate-900">“{data.query}”</span>
                  </p>
                  <ol className="mt-3 space-y-4">
                    {data.results.map((hit, index) => (
                      <li
                        key={hit.chunk_id}
                        className="rounded-md bg-slate-50 p-4 text-sm ring-1 ring-slate-200"
                      >
                        <p className="text-xs font-medium uppercase tracking-wide text-slate-500">
                          Source {index + 1}
                        </p>
                        <h2 className="mt-1 font-semibold text-slate-900">
                          {hit.document_title}
                        </h2>
                        <p className="text-xs text-slate-500">{citationLabel(hit)}</p>
                        <p className="mt-2 whitespace-pre-line text-slate-700">
                          {excerpt(hit.text)}
                        </p>
                        <div className="mt-2 flex flex-wrap gap-1">
                          {matchLabel(hit).map((label) => (
                            <span
                              key={label}
                              className="inline-flex items-center rounded-full bg-white px-2 py-0.5 text-xs text-slate-600 ring-1 ring-inset ring-slate-300"
                            >
                              {label}
                            </span>
                          ))}
                        </div>
                      </li>
                    ))}
                  </ol>
                </>
              )}
            </div>
          )}
        </Card>

        <div className="space-y-6">
          <Card className="p-5">
            <h2 className="text-base font-semibold text-slate-900">Ask the knowledge base</h2>
            <p className="mt-1 mb-4 text-sm text-slate-600">
              The best passages are reranked, then the answer model may only use them and must cite
              them. If nothing is close enough, it says so without calling the model.
            </p>
            <KnowledgeAsk action={askKnowledge} feedbackAction={submitAnswerFeedback} />
          </Card>
          <Card className="p-5 text-sm text-slate-600">
            <h2 className="text-base font-semibold text-slate-900">How ranking works</h2>
            <p className="mt-1">
              Meaning search and keyword search each return candidates; their ranks are fused, then
              a cross-encoder re-scores the top 10. What you see is the final order, with the reason
              for each match.
            </p>
          </Card>
        </div>
      </div>
    </>
  );
}