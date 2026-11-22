import type { ReactNode } from "react";

import type { VideoBrief } from "@/lib/api-types";
import { sourceLabel } from "@/lib/buyer-memory";
import {
  GOAL_LABELS,
  TONE_LABELS,
  knownBadge,
  knownNote,
  languageName,
  scriptBadge,
} from "@/lib/video-brief";

/**
 * The brief for a personalised buyer video (ADR 0041). One column, made for a phone and for paper.
 * Everything anyone wrote is shown as plain text. The CRM makes no video: a person or a tool the
 * organisation trusts does, from this page. Nothing here changes anything.
 */
export function VideoBriefView({
  brief,
  notices = [],
}: {
  brief: VideoBrief;
  notices?: string[];
}) {
  const tooLong = brief.words > brief.word_target;
  return (
    <article className="space-y-6 text-base text-slate-900">
      <header className="border-b border-slate-300 pb-4">
        <p className="text-sm uppercase tracking-wide text-slate-500">
          Video brief
        </p>
        <h1 className="text-2xl font-semibold">Video brief</h1>
        <p className="mt-1 text-lg">For {brief.first_name || "the buyer"}</p>
        <p className="mt-1 text-sm text-slate-700">
          {GOAL_LABELS[brief.goal]} · {languageName(brief.language)} ·{" "}
          {TONE_LABELS[brief.tone]} · {brief.length_seconds} seconds
        </p>
        <p className="mt-1 text-sm text-slate-600">{brief.tone_note}</p>
      </header>
      {notices.map((text) => (
        <p
          key={text}
          role="alert"
          className="rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900"
        >
          {text}
        </p>
      ))}

      <Section title="The script">
        <p
          className={`mb-2 text-sm ${tooLong ? "font-medium text-red-700" : "text-slate-600"}`}
        >
          {brief.words} words; {brief.length_seconds} seconds holds about{" "}
          {brief.word_target}.
        </p>
        <ol className="space-y-3">
          {brief.script.map((line, index) => (
            <li key={index} className="text-base">
              <Badge tone={line.kind === "question" ? "assumption" : "note"}>
                {scriptBadge(line.kind)}
              </Badge>{" "}
              <span lang={brief.language}>{line.text}</span>
              <span className="block text-xs text-slate-500">
                about {line.seconds} s
                {line.cites.length > 0 && ` · from ${line.cites.join(", ")}`}
              </span>
            </li>
          ))}
        </ol>
        <p className="mt-3 text-xs text-slate-500">
          A draft to speak from, not a finished text.
          {brief.language !== "en" &&
            " The Hindi and Telugu wording still needs a read-through by a native speaker."}
        </p>
      </Section>

      <Section title="What it is built from">
        {brief.known.length === 0 ? (
          <p className="text-sm text-slate-600">
            Nothing recorded yet. Add what the buyer tells you to the buyer
            memory first.
          </p>
        ) : (
          <ul className="space-y-3">
            {brief.known.map((k, index) => (
              <li key={index} className="text-sm">
                <Badge tone={k.kind === "fact" ? "fact" : "note"}>
                  {knownBadge(k.kind)}
                </Badge>{" "}
                <span className="font-medium">{k.label}:</span> {k.value}
                <p className="text-xs text-slate-500">
                  {knownNote(k.kind)}
                  {k.kind === "fact" &&
                    k.source &&
                    ` ${sourceLabel(k.source)}.`}
                  {k.kind === "fact" && k.quote && ` "${k.quote}"`}
                  {k.kind === "assumption" &&
                    k.reason &&
                    ` Why we think so: ${k.reason}`}
                  {k.kind === "price" && k.source && ` Source: ${k.source}.`}
                </p>
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section title="Say this">
        <List items={brief.must_say} />
      </Section>
      <Section title="Never say this">
        <List items={brief.must_not_say} />
      </Section>
      <Section title="Consent and privacy">
        <List items={brief.consent_notes} />
      </Section>

      <Section title="Be careful">
        {brief.cautions.length === 0 ? (
          <p className="text-sm text-slate-600">Nothing special to watch.</p>
        ) : (
          <ul className="space-y-2">
            {brief.cautions.map((c, index) => (
              <li key={c.code + index} className="text-sm">
                <Badge tone="caution">Note</Badge> {c.text}
              </li>
            ))}
          </ul>
        )}
      </Section>
    </article>
  );
}

function List({ items }: { items: string[] }) {
  return (
    <ul className="list-disc space-y-1 pl-5 text-sm">
      {items.map((text) => (
        <li key={text}>{text}</li>
      ))}
    </ul>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  const id = `video-brief-${title.toLowerCase().replace(/[^a-z]+/g, "-")}`;
  return (
    <section aria-labelledby={id} className="break-inside-avoid">
      <h2 id={id} className="mb-2 text-lg font-semibold">
        {title}
      </h2>
      {children}
    </section>
  );
}

const TONES = {
  fact: "bg-green-100 text-green-900",
  assumption: "bg-amber-100 text-amber-900",
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
