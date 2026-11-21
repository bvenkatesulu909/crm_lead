"use client";

import { useEffect, useState } from "react";

import type { Fetched } from "@/app/(app)/leads/[id]/call-actions";
import type { ProposalChoice } from "@/app/(app)/leads/[id]/call-notes-actions";
import { buttonClass } from "@/components/ui";
import {
  STATE_LABELS,
  STATE_MEANINGS,
  cleanedText,
  noteCodeText,
  outcomeText,
  stamp,
  type NotesDraft,
  type NotesLine,
  type NotesPage,
  type ProposalOutcome,
  type ProposalPreview,
} from "@/lib/call-notes";
import type { CallListen } from "@/lib/calls";
import { formatDateTime } from "@/lib/format";

export type NotesActions = {
  read: () => Promise<Fetched<NotesPage>>;
  readVersion: (version: number) => Promise<Fetched<NotesDraft>>;
  create: () => Promise<Fetched<NotesDraft>>;
  preview: (
    version: number,
    followUpTask: boolean,
  ) => Promise<Fetched<ProposalPreview>>;
  propose: (
    version: number,
    choice: ProposalChoice,
  ) => Promise<Fetched<ProposalOutcome[]>>;
};

const BADGE: Record<string, string> = {
  stated: "bg-emerald-50 text-emerald-800 ring-emerald-600/20",
  assumed: "bg-amber-50 text-amber-800 ring-amber-600/20",
  unknown: "bg-slate-100 text-slate-700 ring-slate-500/20",
};

type Play = (milliseconds: number) => void;

/** "Listen at 0:06": the moment in the recording where the quoted words are. */
function ListenAt({
  ms,
  play,
  available,
}: {
  ms: number | null;
  play: Play;
  available: boolean;
}) {
  if (ms === null || !available) return null;
  return (
    <button
      type="button"
      className="text-xs font-medium text-brand-700 underline"
      onClick={() => play(ms)}
    >
      Listen at {stamp(ms)}
    </button>
  );
}

function LineView({
  line,
  play,
  audio,
}: {
  line: NotesLine;
  play: Play;
  audio: boolean;
}) {
  const why = noteCodeText(line.note_code);
  return (
    <li className="py-2" data-testid="notes-line" data-state={line.state}>
      <div className="flex flex-wrap items-baseline gap-2">
        <span className="text-sm font-medium text-slate-900">{line.label}</span>
        <span
          data-testid="notes-state"
          className={`inline-flex rounded-full px-2 py-0.5 text-xs font-semibold ring-1 ring-inset ${BADGE[line.state]}`}
        >
          {STATE_LABELS[line.state]}
        </span>
      </div>
      {line.state === "unknown" ? (
        <p className="mt-0.5 text-sm text-slate-600">
          Nothing on this call answers it.
        </p>
      ) : (
        <>
          <p className="mt-0.5 whitespace-pre-wrap text-sm text-slate-900">
            {line.value}
          </p>
          {line.state === "assumed" && line.reason && (
            <p className="mt-0.5 text-xs text-slate-700">
              Why we think so: {line.reason}
            </p>
          )}
          <p
            className="mt-1 whitespace-pre-wrap border-l-2 border-slate-300 pl-2 text-xs text-slate-700"
            data-testid="notes-quote"
          >
            “{line.quote}”
          </p>
          <p className="mt-0.5 text-xs text-slate-600">
            At {stamp(line.start_ms)} · Speaker not verified.{" "}
            <ListenAt ms={line.start_ms} play={play} available={audio} />
          </p>
        </>
      )}
      {why && <p className="mt-0.5 text-xs text-slate-600">{why}</p>}
    </li>
  );
}

function DraftView({
  draft,
  play,
  audio,
}: {
  draft: NotesDraft;
  play: Play;
  audio: boolean;
}) {
  const checklist = draft.lines.filter((l) => l.field !== "note");
  const notes = draft.lines.filter((l) => l.field === "note");
  const cleaned = cleanedText(draft.cleaned_codes);
  return (
    <div className="mt-2" data-testid="notes-draft">
      <p className="text-xs text-slate-700">
        {draft.framework.toUpperCase()} checklist · version {draft.version_no} ·{" "}
        {formatDateTime(draft.created_at)}
      </p>
      <ul className="mt-1 divide-y divide-slate-200">
        {checklist.map((line) => (
          <LineView key={line.position} line={line} play={play} audio={audio} />
        ))}
      </ul>
      {draft.downgraded > 0 && (
        <p className="mt-2 text-xs text-slate-700" role="status">
          {draft.downgraded} answer{draft.downgraded === 1 ? "" : "s"} could not
          be checked against the transcript and{" "}
          {draft.downgraded === 1 ? "is" : "are"} shown as unknown.
        </p>
      )}
      {notes.length > 0 && (
        <div className="mt-3">
          <h4 className="text-sm font-medium text-slate-900">Call notes</h4>
          <ul className="mt-1 divide-y divide-slate-200">
            {notes.map((line) => (
              <li key={line.position} className="py-2" data-testid="notes-note">
                <p className="whitespace-pre-wrap text-sm text-slate-900">
                  {line.value}
                </p>
                <p className="mt-1 whitespace-pre-wrap border-l-2 border-slate-300 pl-2 text-xs text-slate-700">
                  “{line.quote}”
                </p>
                <p className="mt-0.5 text-xs text-slate-600">
                  At {stamp(line.start_ms)} · Speaker not verified.{" "}
                  <ListenAt ms={line.start_ms} play={play} available={audio} />
                </p>
              </li>
            ))}
          </ul>
        </div>
      )}
      {draft.dropped_notes > 0 && (
        <p className="mt-2 text-xs text-slate-700" role="status">
          {draft.dropped_notes} note{draft.dropped_notes === 1 ? "" : "s"} left
          out because the quoted words are not in the transcript.
        </p>
      )}
      {cleaned.map((text) => (
        <p key={text} className="mt-2 text-xs text-slate-700" role="status">
          {text}
        </p>
      ))}
      <dl className="mt-3 space-y-0.5 text-xs text-slate-600">
        {(["stated", "assumed", "unknown"] as const).map((s) => (
          <div key={s} className="flex gap-1">
            <dt className="font-medium">{STATE_LABELS[s]}:</dt>
            <dd>{STATE_MEANINGS[s]}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

/** Suggest the draft to the buyer memory: a preview, then proposals that a different person approves. */
function Suggestions({
  draft,
  actions,
}: {
  draft: NotesDraft;
  actions: NotesActions;
}) {
  const [preview, setPreview] = useState<ProposalPreview | null>(null);
  const [chosen, setChosen] = useState<number[]>([]);
  const [task, setTask] = useState(true);
  const [outcomes, setOutcomes] = useState<ProposalOutcome[] | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function open() {
    setBusy(true);
    setProblem(null);
    setOutcomes(null);
    const result = await actions.preview(draft.version_no, true);
    setBusy(false);
    if (!result.ok) return setProblem(result.message);
    setPreview(result.value);
    setChosen(result.value.memory.map((m) => m.position));
    setTask(result.value.task !== null);
  }

  async function send() {
    setBusy(true);
    setProblem(null);
    const result = await actions.propose(draft.version_no, {
      positions: chosen,
      followUpTask: task,
    });
    setBusy(false);
    if (!result.ok) return setProblem(result.message);
    setOutcomes(result.value);
    setPreview(null);
  }

  const nothing = preview && preview.memory.length === 0 && !preview.task;
  return (
    <div
      className="mt-4 border-t border-slate-200 pt-3"
      data-testid="notes-suggest"
    >
      {!preview && !outcomes && (
        <button
          type="button"
          className={buttonClass("secondary")}
          disabled={busy}
          onClick={open}
        >
          Suggest to buyer memory…
        </button>
      )}
      {problem && (
        <p className="mt-2 text-sm text-red-700" role="alert">
          {problem}
        </p>
      )}
      {preview && (
        <div>
          <p className="text-sm text-slate-800">
            These go to the approval queue. Details are saved as{" "}
            <strong>assumptions, not facts</strong>. A different person must
            approve each one; nothing changes until then.
          </p>
          {nothing && (
            <p className="mt-2 text-sm text-slate-600">
              There is nothing in this draft to suggest.
            </p>
          )}
          <ul className="mt-2 space-y-2">
            {preview.memory.map((m) => (
              <li key={m.position}>
                <label className="flex items-start gap-2 text-sm text-slate-800">
                  <input
                    type="checkbox"
                    className="mt-0.5"
                    checked={chosen.includes(m.position)}
                    onChange={(e) =>
                      setChosen((now) =>
                        e.target.checked
                          ? [...now, m.position]
                          : now.filter((p) => p !== m.position),
                      )
                    }
                  />
                  <span>
                    <span className="font-medium">{m.label}:</span> {m.value}
                    <span className="block text-xs text-slate-600">
                      {m.note}
                    </span>
                  </span>
                </label>
              </li>
            ))}
            {preview.task && (
              <li>
                <label className="flex items-start gap-2 text-sm text-slate-800">
                  <input
                    type="checkbox"
                    className="mt-0.5"
                    checked={task}
                    onChange={(e) => setTask(e.target.checked)}
                  />
                  <span>
                    <span className="font-medium">Follow-up task:</span>{" "}
                    {preview.task.subject}
                    <span className="block text-xs text-slate-600">
                      Due in {preview.task.due_in_days} days.
                    </span>
                  </span>
                </label>
              </li>
            )}
          </ul>
          <div className="mt-3 flex gap-2">
            <button
              type="button"
              className={buttonClass("primary")}
              disabled={busy || (chosen.length === 0 && !task)}
              onClick={send}
            >
              Send for approval
            </button>
            <button
              type="button"
              className={buttonClass("secondary")}
              disabled={busy}
              onClick={() => setPreview(null)}
            >
              Cancel
            </button>
          </div>
        </div>
      )}
      {outcomes && (
        <div role="status" data-testid="notes-outcomes">
          <p className="text-sm text-slate-800">
            Nothing has changed yet. What happened to each suggestion:
          </p>
          <ul className="mt-2 space-y-1 text-sm text-slate-800">
            {outcomes.map((o, i) => (
              <li key={i} data-status={o.status}>
                <span className="font-medium">
                  {o.target === "task" ? "Follow-up task" : o.target}:
                </span>{" "}
                {outcomeText(o)}{" "}
                {o.proposal_link && (
                  <a
                    href={o.proposal_link}
                    className="font-medium text-brand-700 underline"
                  >
                    Open it
                  </a>
                )}
              </li>
            ))}
          </ul>
          <button
            type="button"
            className={`${buttonClass("secondary")} mt-2`}
            onClick={() => setOutcomes(null)}
          >
            Done
          </button>
        </div>
      )}
    </div>
  );
}

/**
 * Call notes and the deal checklist of one recording (ADR 0035). An AI draft, labelled as one:
 * every line says whether it was stated, assumed or unknown, shows the quote and the moment in the
 * call, and says the speaker is not identified. Nothing is changed in the CRM from here except
 * through the approval queue.
 */
export function CallNotesPanel({
  actions,
  canAsk,
  audioAvailable,
  listen,
}: {
  actions: NotesActions;
  canAsk: boolean;
  audioAvailable: boolean;
  listen: () => Promise<Fetched<CallListen>>;
}) {
  const [page, setPage] = useState<NotesPage | null>(null);
  const [shown, setShown] = useState<NotesDraft | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [audio, setAudio] = useState<{ url: string; at: number } | null>(null);

  // `actions` must be stable (the card memoises it): the notes are loaded once per call.
  useEffect(() => {
    let current = true;
    actions.read().then((result) => {
      if (!current) return;
      if (!result.ok) return setProblem(result.message);
      setPage(result.value);
      setShown(result.value.newest);
    });
    return () => {
      current = false;
    };
  }, [actions]);

  async function create() {
    setBusy(true);
    setProblem(null);
    const result = await actions.create();
    setBusy(false);
    if (!result.ok) return setProblem(result.message);
    const draft = result.value;
    setShown(draft);
    setPage((now) => ({
      newest: draft,
      versions: [
        {
          version_no: draft.version_no,
          framework: draft.framework,
          requested_by_user_id: draft.requested_by_user_id,
          created_at: draft.created_at,
        },
        ...(now?.versions ?? []),
      ],
    }));
  }

  async function open(version: number) {
    setBusy(true);
    setProblem(null);
    const result = await actions.readVersion(version);
    setBusy(false);
    if (!result.ok) return setProblem(result.message);
    setShown(result.value);
  }

  const play: Play = async (milliseconds) => {
    setProblem(null);
    const result = await listen();
    if (!result.ok) return setProblem(result.message);
    setAudio({ url: result.value.url, at: Math.floor(milliseconds / 1000) });
  };

  const newest = page?.newest?.version_no ?? null;
  return (
    <section
      className="mt-3 rounded-md border border-slate-200 p-3"
      aria-label="Call notes"
      data-testid="call-notes"
    >
      <h3 className="text-sm font-semibold text-slate-900">
        Call notes and deal checklist
      </h3>
      <p className="mt-0.5 text-xs text-slate-600">
        An AI draft from the transcript. It can be wrong: listen to the moment
        before you rely on a line. Nothing in the CRM has changed.
      </p>
      {!page && !problem && (
        <p className="mt-2 text-sm text-slate-600">Loading call notes…</p>
      )}
      {page && !shown && (
        <p className="mt-2 text-sm text-slate-600">
          No call notes yet for this call.
        </p>
      )}
      {canAsk && page && (
        <div className="mt-2">
          <button
            type="button"
            className={buttonClass("secondary")}
            disabled={busy}
            onClick={create}
          >
            {shown ? "Make new call notes" : "Create call notes"}
          </button>
        </div>
      )}
      {problem && (
        <p className="mt-2 text-sm text-red-700" role="alert">
          {problem}
        </p>
      )}
      {page && page.versions.length > 1 && (
        <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-slate-700">
          <span>Versions:</span>
          {page.versions.map((v) => (
            <button
              key={v.version_no}
              type="button"
              className={`rounded px-2 py-0.5 ring-1 ring-inset ${shown?.version_no === v.version_no ? "bg-slate-200 ring-slate-400" : "ring-slate-300"}`}
              aria-pressed={shown?.version_no === v.version_no}
              disabled={busy}
              onClick={() => open(v.version_no)}
            >
              {v.version_no}
              {v.version_no === newest ? " (newest)" : ""}
            </button>
          ))}
        </div>
      )}
      {shown && <DraftView draft={shown} play={play} audio={audioAvailable} />}
      {audio && (
        <div className="mt-2">
          <audio
            controls
            autoPlay
            src={`${audio.url}#t=${audio.at}`}
            className="w-full"
          />
          <p className="mt-1 text-xs text-slate-600">
            Starts at {stamp(audio.at * 1000)}. The link works for one minute.
          </p>
        </div>
      )}
      {canAsk && shown && (
        <Suggestions key={shown.version_no} draft={shown} actions={actions} />
      )}
    </section>
  );
}
