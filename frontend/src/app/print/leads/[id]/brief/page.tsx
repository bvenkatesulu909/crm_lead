import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { PrintButton } from "@/components/print-button";
import { SiteBriefView } from "@/components/site-brief-view";
import { ApiError, toErrorInfo } from "@/lib/api-error";
import type { SiteBrief } from "@/lib/api-types";
import { isUuid } from "@/lib/communications";
import { apiFetch } from "@/lib/server/api";

export const metadata: Metadata = { title: "Site visit brief" };

const PLACE_MAX = 100;

/**
 * The rep's brief before a site visit (ADR 0029): one column, made for a phone and for paper (use
 * the browser's print dialog). The API builds it on demand from what the CRM holds and decides who
 * may see it: a lead the person may not read is "not found". The optional place is typed for this
 * one view and is never stored.
 */
export default async function PrintBriefPage({
  params,
  searchParams,
}: PageProps<"/print/leads/[id]/brief">) {
  const { id } = await params;
  if (!isUuid(id)) notFound();
  const raw = (await searchParams).place;
  const typed = (Array.isArray(raw) ? raw[0] : raw)?.trim().slice(0, 400);
  const path = (place?: string) =>
    place
      ? `/leads/${id}/brief?place=${encodeURIComponent(place)}`
      : `/leads/${id}/brief`;

  let brief: SiteBrief;
  let placeError: string | null = null;
  try {
    brief = await apiFetch<SiteBrief>(path(typed));
  } catch (error) {
    if (
      error instanceof ApiError &&
      (error.status === 404 || error.status === 403)
    )
      notFound();
    if (
      typed &&
      error instanceof ApiError &&
      error.status === 422 &&
      error.problem.code === "brief_place_invalid"
    ) {
      // A refused place never blocks the brief: say why, then build it without one.
      placeError = toErrorInfo(error).message;
      brief = await apiFetch<SiteBrief>(path());
    } else throw error;
  }

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
        className="mb-6 flex flex-wrap items-end gap-2 print:hidden"
      >
        <div className="flex-1">
          <label htmlFor="place" className="text-sm font-medium">
            Where is the visit?
          </label>
          <input
            id="place"
            name="place"
            defaultValue={brief.place ?? ""}
            maxLength={PLACE_MAX}
            placeholder="For example: Skyline Towers, tower B"
            className="mt-1 block w-full rounded-md border-0 bg-white px-3 py-2 text-sm ring-1 ring-inset ring-slate-300 focus:ring-2 focus:ring-brand-600"
          />
        </div>
        <button
          type="submit"
          className="rounded-md bg-white px-3.5 py-2 text-sm font-semibold text-slate-700 shadow-sm ring-1 ring-inset ring-slate-300 hover:bg-slate-50"
        >
          Update
        </button>
      </form>
      <SiteBriefView brief={brief} placeError={placeError} />
      <footer className="mt-8 border-t border-slate-200 pt-3 text-xs text-slate-500 print:mt-4">
        Built from the CRM when this page was opened; nothing here is saved. Personal details - keep
        this page to yourself.
      </footer>
    </main>
  ); // prettier-ignore
}
