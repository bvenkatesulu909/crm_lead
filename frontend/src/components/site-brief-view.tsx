import type { ReactNode } from "react";

import type { SiteBrief } from "@/lib/api-types";
import { sourceLabel } from "@/lib/buyer-memory";
import { formatDate, formatDateTime } from "@/lib/format";
import { askBadge, dueText, entryKind, statusText } from "@/lib/site-brief";

/**
 * The rep's brief before a site visit (ADR 0029). Made for a phone and for paper: one column, big
 * type, every line marked Fact, Assumption, Ask, Confirm or Note. Everything anyone wrote is shown
 * as plain text. Nothing here changes anything.
 */
export function SiteBriefView({
  brief,
  placeError,
}: {
  brief: SiteBrief;
  placeError?: string | null;
}) {
  const { buyer } = brief;
  return (
    <article className="space-y-6 text-base text-slate-900">
      <header className="border-b border-slate-300 pb-4">
        <p className="text-sm uppercase tracking-wide text-slate-500">
          Site visit brief
        </p>
        <h1 className="text-2xl font-semibold">Site visit brief</h1>
        <p className="mt-1 text-lg">{buyer.name}</p>
        {brief.place && (
          <p className="mt-1 text-slate-700">Visit at: {brief.place}</p>
        )}
        <p className="mt-1 text-sm text-slate-500">
          As of {formatDateTime(brief.as_of)}
        </p>
      </header>
      {placeError && (
        <p
          role="alert"
          className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800"
        >
          {placeError}
        </p>
      )}

      <Section title="The buyer">
        <dl className="grid grid-cols-2 gap-x-4 gap-y-3 text-sm">
          <Row label="Name">{buyer.name}</Row>
          <Row label="Status">{statusText(buyer.status)}</Row>
          <Row label="Call in">{buyer.language_label ?? "—"}</Row>
          <Row label="Phone">{buyer.phone ?? "—"}</Row>
          <Row label="E-mail">{buyer.email ?? "—"}</Row>
          <Row label="Source">{buyer.source ?? "—"}</Row>
          <Row label="Owner">{buyer.owner ?? "—"}</Row>
        </dl>
      </Section>

      <Section title="What we know">
        {brief.facts.length === 0 && brief.assumptions.length === 0 && (
          <p className="text-sm text-slate-600">
            Nothing recorded yet. Ask the questions below and add the answers to
            the buyer memory.
          </p>
        )}
        <ul className="space-y-3">
          {brief.facts.map((f) => (
            <li key={f.key + f.recorded_on} className="text-sm">
              <Badge tone="fact">Fact</Badge>{" "}
              <span className="font-medium">{f.label}:</span> {f.value}
              <p className="text-xs text-slate-500">
                {sourceLabel(f.source)}
                {f.quote ? ` - "${f.quote}"` : ""} · {formatDate(f.recorded_on)}
              </p>
            </li>
          ))}
          {brief.assumptions.map((g) => (
            <li key={g.key + g.recorded_on} className="text-sm">
              <Badge tone="assumption">Assumption</Badge>{" "}
              <span className="font-medium">{g.label}:</span> {g.value}
              <p className="text-xs text-slate-600">
                Confirm on the visit. Why we think so: {g.reason}
              </p>
            </li>
          ))}
        </ul>
      </Section>

      <Section title="Ask on the visit">
        {brief.ask.length === 0 ? (
          <p className="text-sm text-slate-600">Nothing left to ask.</p>
        ) : (
          <ol className="space-y-2">
            {brief.ask.map((a) => (
              <li key={a.kind + a.key} className="text-sm">
                <Badge tone={a.kind === "confirm" ? "assumption" : "gap"}>
                  {askBadge(a.kind)}
                </Badge>{" "}
                {a.text}
              </li>
            ))}
          </ol>
        )}
      </Section>

      <Section title="Where we left off">
        {brief.recent.length === 0 ? (
          <p className="text-sm text-slate-600">
            Nothing logged on this lead yet.
          </p>
        ) : (
          <ul className="space-y-2">
            {brief.recent.map((e) => (
              <li key={e.kind + e.occurred_at + e.subject} className="text-sm">
                <Badge tone="note">{entryKind(e.kind)}</Badge>{" "}
                <span className="font-medium">{e.subject}</span>
                <span className="text-xs text-slate-500">
                  {" "}
                  · {formatDate(e.occurred_at)}
                </span>
                {e.excerpt && (
                  <p className="text-xs whitespace-pre-line text-slate-600">
                    {e.excerpt}
                  </p>
                )}
              </li>
            ))}
          </ul>
        )}
        <h3 className="mt-4 text-sm font-semibold">Open follow-ups</h3>
        {brief.tasks.length === 0 ? (
          <p className="mt-1 text-sm text-slate-600">No open follow-ups.</p>
        ) : (
          <ul className="mt-1 space-y-1">
            {brief.tasks.map((t) => (
              <li key={t.subject + (t.due_at ?? "")} className="text-sm">
                <span className="font-medium">{t.subject}</span>{" "}
                <span
                  className={
                    t.overdue ? "text-red-700" : "text-xs text-slate-500"
                  }
                >
                  · {dueText(t)}
                </span>
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section title="Be careful">
        {brief.cautions.length === 0 ? (
          <p className="text-sm text-slate-600">Nothing special to watch.</p>
        ) : (
          <ul className="space-y-2">
            {brief.cautions.map((c) => (
              <li key={c.code} className="text-sm">
                <Badge tone="caution">Note</Badge> {c.text}
              </li>
            ))}
          </ul>
        )}
      </Section>
    </article>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  const id = `brief-${title.toLowerCase().replace(/[^a-z]+/g, "-")}`;
  return (
    <section aria-labelledby={id} className="break-inside-avoid">
      <h2 id={id} className="mb-2 text-lg font-semibold">
        {title}
      </h2>
      {children}
    </section>
  );
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <dt className="text-xs uppercase tracking-wide text-slate-500">
        {label}
      </dt>
      <dd className="break-words">{children}</dd>
    </div>
  );
}

const TONES = {
  fact: "bg-green-100 text-green-900",
  assumption: "bg-amber-100 text-amber-900",
  gap: "bg-slate-200 text-slate-800",
  note: "bg-blue-100 text-blue-900",
  caution: "bg-red-100 text-red-900",
} as const;

function Badge({
  tone,
  children,
}: {
  tone: keyof typeof TONES;
  children: ReactNode;
}) {
  return (
    <span
      className={`inline-block rounded px-1.5 py-0.5 text-xs font-semibold ${TONES[tone]}`}
    >
      {children}
    </span>
  );
}
