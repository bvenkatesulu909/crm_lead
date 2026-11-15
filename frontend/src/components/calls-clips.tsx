"use client";

import { useCallback, useEffect, useState } from "react";

import type { Fetched } from "@/app/(app)/leads/[id]/call-actions";
import { buttonClass } from "@/components/ui";
import {
  checkNewClip,
  clipRange,
  clipStatusLabel,
  formatDuration,
  type CallClip,
  type CallDetail,
  type CallListen,
  type ClipInput,
} from "@/lib/calls";

/** The clip actions of ONE recording (the recording's id is already filled in). */
export type ClipsActions = {
  list: () => Promise<Fetched<CallClip[]>>;
  create: (input: ClipInput) => Promise<Fetched<CallClip>>;
  edit: (
    clipId: string,
    input: { title: string; note: string },
  ) => Promise<Fetched<CallClip>>;
  remove: (clipId: string) => Promise<Fetched<null>>;
  listen: (clipId: string) => Promise<Fetched<CallListen>>;
};

/** How often the list looks again while a clip is being cut. */
export const CLIP_REFRESH_MS = 4000;

const field =
  "mt-1 block w-full rounded-md border border-slate-300 px-3 py-2 text-sm";

function ClipItem({
  clip,
  canWrite,
  actions,
  onChanged,
}: {
  clip: CallClip;
  canWrite: boolean;
  actions: ClipsActions;
  onChanged: () => void;
}) {
  const [audio, setAudio] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [title, setTitle] = useState(clip.title);
  const [note, setNote] = useState(clip.note ?? "");
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  async function run<T>(work: () => Promise<Fetched<T>>, then: (v: T) => void) {
    setBusy(true);
    setProblem(null);
    const result = await work();
    setBusy(false);
    if (result.ok) then(result.value);
    else setProblem(result.message);
  }

  const canListen =
    clip.status === "ready" && clip.audio_available && !clip.audio_deleted_at;

  return (
    <li className="py-3" data-testid="clip-item">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="text-sm font-medium text-slate-900">{clip.title}</p>
        <span className="text-xs text-slate-600">
          <span className="tabular-nums">{clipRange(clip)}</span> ·{" "}
          {clipStatusLabel(clip)}
        </span>
      </div>
      {clip.note && (
        <p className="mt-1 whitespace-pre-wrap text-sm text-slate-700">
          {clip.note}
        </p>
      )}
      {clip.excerpt && (
        <p
          data-testid="clip-excerpt"
          className="mt-1 whitespace-pre-wrap rounded-md bg-slate-50 p-2 text-xs text-slate-700"
        >
          {clip.excerpt}
        </p>
      )}
      {editing ? (
        <div className="mt-2 space-y-2">
          <label className="block text-xs font-medium text-slate-700">
            Clip title
            <input
              className={field}
              value={title}
              maxLength={100}
              onChange={(e) => setTitle(e.target.value)}
            />
          </label>
          <label className="block text-xs font-medium text-slate-700">
            Clip note
            <textarea
              className={field}
              value={note}
              maxLength={500}
              rows={2}
              onChange={(e) => setNote(e.target.value)}
            />
          </label>
          <div className="flex gap-2">
            <button
              type="button"
              className={buttonClass("primary")}
              disabled={busy}
              onClick={() =>
                run(
                  () => actions.edit(clip.id, { title, note }),
                  () => {
                    setEditing(false);
                    onChanged();
                  },
                )
              }
            >
              Save
            </button>
            <button
              type="button"
              className={buttonClass("secondary")}
              onClick={() => setEditing(false)}
            >
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <div className="mt-2 flex flex-wrap items-center gap-2">
          {canListen && (
            <button
              type="button"
              className={buttonClass("secondary")}
              disabled={busy}
              onClick={() =>
                run(
                  () => actions.listen(clip.id),
                  (link) => setAudio(link.url),
                )
              }
            >
              Listen
            </button>
          )}
          {canWrite && !confirming && (
            <>
              <button
                type="button"
                className={buttonClass("secondary")}
                onClick={() => setEditing(true)}
              >
                Edit
              </button>
              <button
                type="button"
                className={buttonClass("secondary")}
                onClick={() => setConfirming(true)}
              >
                Delete
              </button>
            </>
          )}
          {canWrite && confirming && (
            <>
              <span className="text-sm text-slate-700">
                Delete this clip and its audio?
              </span>
              <button
                type="button"
                className={buttonClass("danger")}
                disabled={busy}
                onClick={() =>
                  run(
                    () => actions.remove(clip.id),
                    () => {
                      setConfirming(false);
                      onChanged();
                    },
                  )
                }
              >
                Yes, delete
              </button>
              <button
                type="button"
                className={buttonClass("secondary")}
                onClick={() => setConfirming(false)}
              >
                Cancel
              </button>
            </>
          )}
        </div>
      )}
      {problem && (
        <p className="mt-2 text-sm text-red-700" role="alert">
          {problem}
        </p>
      )}
      {audio && (
        <div className="mt-2">
          <audio controls autoPlay src={audio} className="w-full" />
          <p className="mt-1 text-xs text-slate-600">
            The link works for one minute.
          </p>
        </div>
      )}
    </li>
  );
}

/**
 * Highlight clips of one recording (ADR 0033): short pieces of the call, with a title and the
 * transcript lines inside them. People who may change the call can make, edit and delete clips (the
 * API checks again); everyone who may read it can listen. Everything a person typed is shown as
 * plain text.
 */
export function ClipsPanel({
  call,
  canWrite,
  actions,
}: {
  call: CallDetail;
  canWrite: boolean;
  actions: ClipsActions;
}) {
  const [clips, setClips] = useState<CallClip[] | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [title, setTitle] = useState("");
  const [note, setNote] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [makeProblem, setMakeProblem] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const reload = useCallback(async () => {
    const result = await actions.list();
    if (result.ok) {
      setClips(result.value);
      setProblem(null);
    } else setProblem(result.message);
  }, [actions]);

  useEffect(() => {
    // Load once per recording (the actions object is recreated on every render of the parent).
    let stale = false;
    void actions.list().then((result) => {
      if (stale) return;
      if (result.ok) {
        setClips(result.value);
        setProblem(null);
      } else setProblem(result.message);
    });
    return () => {
      stale = true;
    };
    // Also look again when the recording's audio is deleted: its clips lose theirs with it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [call.id, call.audio_deleted_at]);

  const waiting = clips?.some((c) => c.status === "queued") ?? false;
  useEffect(() => {
    if (!waiting) return;
    const timer = setInterval(() => void reload(), CLIP_REFRESH_MS);
    return () => clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [waiting]);

  async function make(event: React.FormEvent) {
    event.preventDefault();
    setMakeProblem(null);
    const input: ClipInput = {
      start,
      end,
      title,
      note,
      duration: call.duration_seconds,
    };
    const checked = checkNewClip(input);
    setErrors(checked.ok ? {} : checked.fieldErrors);
    if (!checked.ok) return;
    setBusy(true);
    const result = await actions.create(input);
    setBusy(false);
    if (!result.ok) return setMakeProblem(result.message);
    setStart("");
    setEnd("");
    setTitle("");
    setNote("");
    await reload();
  }

  const segments = call.segments ?? [];
  return (
    <div className="mt-3 border-t border-slate-200 pt-3" data-testid="clips">
      <h3 className="text-sm font-semibold text-slate-900">Highlight clips</h3>
      {problem && (
        <p className="mt-2 text-sm text-red-700" role="alert">
          {problem}
        </p>
      )}
      {clips !== null &&
        (clips.length === 0 ? (
          <p className="mt-2 text-sm text-slate-600">
            No clips yet.
            {canWrite &&
              " Pick the start and the end of a moment below to make one."}
          </p>
        ) : (
          <ul className="mt-1 divide-y divide-slate-200">
            {clips.map((clip) => (
              <ClipItem
                key={clip.id}
                clip={clip}
                canWrite={canWrite}
                actions={actions}
                onChanged={() => void reload()}
              />
            ))}
          </ul>
        ))}
      {canWrite && call.audio_available && (
        <form onSubmit={make} className="mt-3 space-y-3" noValidate>
          <p className="text-xs text-slate-600">
            A clip is 3 seconds to 2 minutes, cut from the cleaned copy. Pick
            the moment from the transcript or type the times.
          </p>
          {segments.length > 0 && (
            <ol className="max-h-48 space-y-1 overflow-y-auto rounded-md bg-slate-50 p-2 text-sm">
              {segments.map((s, i) => (
                <li
                  key={i}
                  data-testid="clip-pick-line"
                  className="flex flex-wrap items-center gap-2"
                >
                  <span className="w-12 shrink-0 text-xs tabular-nums text-slate-500">
                    {formatDuration(s.start)}
                  </span>
                  <span className="min-w-0 flex-1 whitespace-pre-wrap">
                    {s.text}
                  </span>
                  <button
                    type="button"
                    className="text-xs font-medium text-brand-700 hover:underline"
                    onClick={() => setStart(formatDuration(s.start))}
                  >
                    Start here
                  </button>
                  <button
                    type="button"
                    className="text-xs font-medium text-brand-700 hover:underline"
                    onClick={() => setEnd(formatDuration(s.end))}
                  >
                    End here
                  </button>
                </li>
              ))}
            </ol>
          )}
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="block text-sm font-medium text-slate-700">
              Start (m:ss)
              <input
                className={field}
                value={start}
                onChange={(e) => setStart(e.target.value)}
                inputMode="numeric"
              />
              {errors.start && (
                <span className="mt-1 block text-xs text-red-700">
                  {errors.start}
                </span>
              )}
            </label>
            <label className="block text-sm font-medium text-slate-700">
              End (m:ss)
              <input
                className={field}
                value={end}
                onChange={(e) => setEnd(e.target.value)}
                inputMode="numeric"
              />
              {errors.end && (
                <span className="mt-1 block text-xs text-red-700">
                  {errors.end}
                </span>
              )}
            </label>
          </div>
          <label className="block text-sm font-medium text-slate-700">
            Title
            <input
              className={field}
              value={title}
              maxLength={100}
              onChange={(e) => setTitle(e.target.value)}
            />
            {errors.title && (
              <span className="mt-1 block text-xs text-red-700">
                {errors.title}
              </span>
            )}
          </label>
          <label className="block text-sm font-medium text-slate-700">
            Note (optional)
            <textarea
              className={field}
              value={note}
              maxLength={500}
              rows={2}
              onChange={(e) => setNote(e.target.value)}
            />
            {errors.note && (
              <span className="mt-1 block text-xs text-red-700">
                {errors.note}
              </span>
            )}
          </label>
          {makeProblem && (
            <p className="text-sm text-red-700" role="alert">
              {makeProblem}
            </p>
          )}
          <button
            type="submit"
            className={buttonClass("primary")}
            disabled={busy}
          >
            Make clip
          </button>
        </form>
      )}
    </div>
  );
}
