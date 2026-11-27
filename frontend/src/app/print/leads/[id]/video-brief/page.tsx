import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { PrintButton } from "@/components/print-button";
import { SavedScripts } from "@/components/saved-scripts";
import { VideoScriptEditor } from "@/components/video-script-editor";
import { VideoBriefView } from "@/components/video-brief-view";
import { ApiError } from "@/lib/api-error";
import type {
  Lead,
  QuotePage,
  ScriptPage,
  ScriptRead,
  VideoBrief,
} from "@/lib/api-types";
import { isUuid } from "@/lib/communications";
import { canWriteVideoBrief } from "@/lib/permissions";
import { apiFetch, getMe } from "@/lib/server/api";
import { saveVideoScript } from "./actions";
import {
  GOAL_LABELS,
  LENGTHS,
  TONE_LABELS,
  briefPath,
  languageName,
  parseChoices,
  quoteOptionLabel,
  quoteProblemText,
  quotesPath,
  LANGUAGES,
} from "@/lib/video-brief";

export const metadata: Metadata = { title: "Video brief" };

const SELECT =
  "mt-1 block w-full rounded-md border-0 bg-white px-3 py-2 text-sm ring-1 ring-inset ring-slate-300 focus:ring-2 focus:ring-brand-600";

/**
 * The brief for a personalised buyer video (ADR 0041): one column, made for a phone and for paper.
 * The API builds it on demand and decides who may see it: a lead the person may not read is "not
 * found". The choices (goal, language, tone, length, quote) are in the address, checked against
 * fixed lists here and again by the API. Nothing is stored.
 */
export default async function VideoBriefPage({
  params,
  searchParams,
}: PageProps<"/print/leads/[id]/video-brief">) {
  const { id } = await params;
  if (!isUuid(id)) notFound();
  const query = await searchParams;
  const choices = parseChoices(query);
  // Only a plain number may be shown as 'saved as version N'.
  const savedRaw = Array.isArray(query.saved) ? query.saved[0] : query.saved;
  const saved = /^\d{1,4}$/.test(savedRaw ?? "") ? (savedRaw as string) : "";

  // The lead first: a lead nobody may read stops here, before anything else is asked.
  let lead: Lead;
  try {
    lead = await apiFetch<Lead>(`/leads/${id}`);
  } catch (error) {
    if (
      error instanceof ApiError &&
      (error.status === 404 || error.status === 403)
    )
      notFound();
    throw error;
  }

  // Only a lead that became an account can have quotes.
  const quotes: QuotePage["items"] = lead.converted_account_id
    ? (
        await apiFetch<QuotePage>(quotesPath(lead.converted_account_id)).catch(
          () => ({ items: [] }) as unknown as QuotePage,
        )
      ).items
    : [];

  const notices: string[] = [];
  let brief: VideoBrief;
  try {
    brief = await apiFetch<VideoBrief>(briefPath(id, choices));
  } catch (error) {
    if (error instanceof ApiError && choices.quoteId) {
      const text = quoteProblemText(error.problem.code);
      if (text) {
        // A refused quote never blocks the brief: say why, then build it without prices.
        notices.push(text);
        brief = await apiFetch<VideoBrief>(
          briefPath(id, { ...choices, quoteId: "" }),
        );
        return page(
          id,
          choices,
          quotes,
          brief,
          notices,
          await extras(id, saved),
        );
      }
    }
    if (
      error instanceof ApiError &&
      (error.status === 404 || error.status === 403)
    )
      notFound();
    throw error;
  }
  return page(id, choices, quotes, brief, notices, await extras(id, saved));
}

/** The saved scripts and whether this person may write one. Neither may stop the brief. */
async function extras(id: string, saved: string) {
  let scripts: ScriptRead[] | null = null;
  try {
    scripts =
      (await apiFetch<ScriptPage>(`/leads/${id}/video-scripts`))?.items ?? null;
  } catch {
    scripts = null;
  }
  let canWrite = false;
  try {
    canWrite = canWriteVideoBrief(await getMe());
  } catch {
    canWrite = false;
  }
  return { scripts, canWrite, saved };
}

function page(
  id: string,
  choices: ReturnType<typeof parseChoices>,
  quotes: QuotePage["items"],
  brief: VideoBrief,
  notices: string[],
  more: {
    scripts: ScriptRead[] | null;
    canWrite: boolean;
    saved: string;
  },
) {
  return (
    <main className="mx-auto max-w-2xl bg-white p-5 text-slate-900 sm:p-8 print:p-0">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3 print:hidden">
        <Link
          href={`/leads/${id}`}
          className="text-sm font-medium text-brand-700 underline"
        >
          ← Back to the lead
        </Link>
        <PrintButton />
      </div>
      <form
        method="get"
        className="mb-6 grid grid-cols-2 items-end gap-3 print:hidden"
      >
        <div>
          <label htmlFor="goal" className="text-sm font-medium">
            What is the video for?
          </label>
          <select id="goal" name="goal" defaultValue={choices.goal} className={SELECT}>
            {Object.entries(GOAL_LABELS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label htmlFor="language" className="text-sm font-medium">
            Language
          </label>
          <select
            id="language"
            name="language"
            defaultValue={choices.language}
            className={SELECT}
          >
            <option value="">The buyer&apos;s own language</option>
            {LANGUAGES.map((code) => (
              <option key={code} value={code}>
                {languageName(code)}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label htmlFor="tone" className="text-sm font-medium">
            Tone
          </label>
          <select id="tone" name="tone" defaultValue={choices.tone} className={SELECT}>
            {Object.entries(TONE_LABELS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label htmlFor="length" className="text-sm font-medium">
            Length
          </label>
          <select
            id="length"
            name="length"
            defaultValue={String(choices.length)}
            className={SELECT}
          >
            {LENGTHS.map((seconds) => (
              <option key={seconds} value={seconds}>
                {seconds} seconds
              </option>
            ))}
          </select>
        </div>
        {quotes.length > 0 && (
          <div className="col-span-2">
            <label htmlFor="quote_id" className="text-sm font-medium">
              Quote to take the prices from
            </label>
            <select
              id="quote_id"
              name="quote_id"
              defaultValue={choices.quoteId}
              className={SELECT}
            >
              <option value="">No prices</option>
              {quotes.map((q) => (
                <option key={q.id} value={q.id}>
                  {quoteOptionLabel(q)}
                </option>
              ))}
            </select>
          </div>
        )}
        <button
          type="submit"
          className="col-span-2 rounded-md bg-white px-3.5 py-2 text-sm font-semibold text-slate-700 shadow-sm ring-1 ring-inset ring-slate-300 hover:bg-slate-50"
        >
          Update the brief
        </button>
      </form>
      {more.saved && (
        <p
          role="status"
          className="mb-4 rounded-md border border-green-200 bg-green-50 px-4 py-3 text-sm text-green-900 print:hidden"
        >
          Your script was saved as version {more.saved}.
        </p>
      )}
      <VideoBriefView brief={brief} notices={notices} />
      {more.canWrite && (
        <div className="mt-8">
          <VideoScriptEditor
            leadId={id}
            brief={brief}
            action={saveVideoScript}
            initialText={brief.script.map((line) => line.text).join("\n")}
            quoteId={choices.quoteId}
          />
        </div>
      )}
      {more.scripts && <SavedScripts scripts={more.scripts} />}
      <footer className="mt-8 border-t border-slate-200 pt-3 text-xs text-slate-500 print:mt-4">
        Built from the CRM when this page was opened; nothing here is saved. The CRM makes no
        video - a person or a tool your organisation trusts does, from this brief.
      </footer>
    </main>
  ); // prettier-ignore
}
