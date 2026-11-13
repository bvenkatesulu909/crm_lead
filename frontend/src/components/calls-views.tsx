"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import type {
  Fetched,
  NewCallInfo,
  StartResult,
} from "@/app/(app)/leads/[id]/call-actions";
import { ActionDialog, DialogField } from "@/components/action-dialog";
import { UploadProgress } from "@/components/upload-progress";
import { buttonClass } from "@/components/ui";
import {
  ACCEPT,
  CALL_LANGUAGES,
  failureText,
  formatDuration,
  formatSize,
  isWorking,
  languageLabel,
  statusLabel,
  type CallDetail,
  type CallListen,
  type CallRecording,
} from "@/lib/calls";
import type { DialogState } from "@/lib/dialog-state";
import { initialDialogState } from "@/lib/dialog-state";
import { directUpload } from "@/lib/direct-upload";
import { formatDateTime } from "@/lib/format";

type Action = (state: DialogState, formData: FormData) => Promise<DialogState>;

export type CallsActions = {
  start: (info: NewCallInfo) => Promise<StartResult>;
  finish: (callId: string, previous: DialogState) => Promise<DialogState>;
  deleteAudio: (callId: string, previous: DialogState) => Promise<DialogState>;
  listen: (callId: string) => Promise<Fetched<CallListen>>;
  read: (callId: string) => Promise<Fetched<CallDetail>>;
};

/** How often the card looks again while a recording is being processed. */
export const REFRESH_MS = 8000;

/** 125.5 -> "2:05" (the start of a segment). */
const stamp = (seconds: number) => formatDuration(seconds);

/**
 * Add a recording of a call. The buyer's consent is a required tick that is stored with who ticked
 * it and when; the file goes from the browser straight to the file store (ADR 0025).
 */
export function AddCallDialog({
  start,
  finish,
  closeWhen,
}: Pick<CallsActions, "start" | "finish"> & { closeWhen?: unknown }) {
  const [percent, setPercent] = useState<number | null>(null);
  // Kept in state so a refused attempt does not empty the form (React resets uncontrolled fields).
  const [language, setLanguage] = useState("hi");
  const [consent, setConsent] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);

  async function action(
    previous: DialogState,
    formData: FormData,
  ): Promise<DialogState> {
    const refused = (
      fieldErrors: Record<string, string>,
      error: DialogState["error"] = null,
    ): DialogState => {
      setPercent(null);
      return { attempt: previous.attempt + 1, fieldErrors, error };
    };
    const file = fileInput.current?.files?.[0] ?? formData.get("file");
    if (!(file instanceof File) || file.size === 0)
      return refused({ file: "Choose a recording." });
    setPercent(0);
    const outcome = await directUpload(
      file,
      () => start({ fileName: file.name, size: file.size, language, consent }),
      (callId) => finish(callId, previous),
      setPercent,
    );
    if (!outcome.ok) return refused(outcome.fieldErrors, outcome.error);
    setPercent(null); // only reached when finishing failed (success navigates away)
    return outcome.result;
  }

  return (
    <ActionDialog triggerLabel="Add a call recording" triggerVariant="secondary" title="Add a call recording"
      description="MP3, M4A, WAV, OGG, WebM or AMR - up to 100 MB and 60 minutes. The recording is cleaned and turned into text automatically; the text can contain mistakes."
      confirmLabel="Add" action={action} initialState={initialDialogState} closeWhen={closeWhen}>
      {(errors) => (
        <>
          <DialogField id="call-file" label="Recording" error={errors.file}>
            {(p) => <input ref={fileInput} type="file" name="file" accept={ACCEPT} required {...p} />}
          </DialogField>
          <DialogField id="call-language" label="Language of the call" error={errors.language}>
            {(p) => (
              <select name="language" value={language} onChange={(e) => setLanguage(e.target.value)} {...p}>
                {CALL_LANGUAGES.map((l) => (
                  <option key={l.value} value={l.value}>{l.label}</option>
                ))}
              </select>
            )}
          </DialogField>
          <div>
            <label className="flex items-start gap-2 text-sm text-slate-700">
              <input type="checkbox" name="consent" checked={consent}
                onChange={(e) => setConsent(e.target.checked)}
                aria-describedby="call-consent-error"
                className="mt-0.5 h-4 w-4 rounded border-slate-300 text-brand-600" />
              <span>The buyer agreed to this call being recorded.</span>
            </label>
            {errors.consent && (
              <p id="call-consent-error" role="alert" className="mt-1 text-sm text-red-700">{errors.consent}</p>
            )}
          </div>
          <UploadProgress percent={percent} />
        </>
      )}
    </ActionDialog>
  ); // prettier-ignore
}

function DeleteAudioDialog({
  action,
  name,
  closeWhen,
}: {
  action: Action;
  name: string;
  closeWhen: unknown;
}) {
  return (
    <ActionDialog triggerLabel="Delete audio" triggerVariant="secondary" title={`Delete the audio of ${name}?`}
      description="The recording and its cleaned copy are deleted and can't be brought back. The written transcript and the record that the buyer agreed stay."
      confirmLabel="Delete audio" confirmVariant="danger" action={action} initialState={initialDialogState} closeWhen={closeWhen} />
  ); // prettier-ignore
}

/** The transcript of one recording: plain text, with the time each stretch started. */
export function TranscriptPanel({ detail }: { detail: CallDetail }) {
  const segments = detail.segments ?? [];
  return (
    <div
      className="mt-2 rounded-md bg-slate-50 p-3"
      data-testid="call-transcript"
    >
      <p className="text-xs text-slate-600">
        Automatic transcript - it can contain mistakes. Check it against the
        recording before you rely on it.
      </p>
      {segments.length > 0 ? (
        <ol className="mt-2 space-y-1 text-sm text-slate-900">
          {segments.map((s, i) => (
            <li key={i} className="flex gap-3">
              <span className="w-12 shrink-0 text-xs tabular-nums text-slate-500">
                {stamp(s.start)}
              </span>
              <span className="whitespace-pre-wrap">{s.text}</span>
            </li>
          ))}
        </ol>
      ) : (
        <p className="mt-2 whitespace-pre-wrap text-sm text-slate-900">
          {detail.transcript}
        </p>
      )}
    </div>
  );
}

function CallItem({
  call,
  canWrite,
  actions,
}: {
  call: CallRecording;
  canWrite: boolean;
  actions: CallsActions;
}) {
  const [audio, setAudio] = useState<CallListen | null>(null);
  const [detail, setDetail] = useState<CallDetail | null>(null);
  const [open, setOpen] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function listen() {
    setBusy(true);
    setProblem(null);
    const result = await actions.listen(call.id);
    setBusy(false);
    if (result.ok) setAudio(result.value);
    else setProblem(result.message);
  }

  async function toggleTranscript() {
    if (open) return setOpen(false);
    setProblem(null);
    if (!detail) {
      setBusy(true);
      const result = await actions.read(call.id);
      setBusy(false);
      if (!result.ok) return setProblem(result.message);
      setDetail(result.value);
    }
    setOpen(true);
  }

  const facts = [
    languageLabel(call.language),
    formatDuration(call.duration_seconds),
    formatSize(call.size_bytes),
    formatDateTime(call.created_at),
  ].filter(Boolean);

  return (
    <li className="py-3" data-testid="call-item">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="text-sm font-medium text-slate-900 break-all">
          {call.file_name}
        </p>
        <span
          className="text-xs font-medium text-slate-700"
          data-testid="call-status"
        >
          {statusLabel(call)}
        </span>
      </div>
      <p className="mt-0.5 text-xs text-slate-600">{facts.join(" · ")}</p>
      {call.status === "failed" && (
        <p className="mt-1 text-sm text-red-700" role="status">
          {failureText(call.failure_code)}
        </p>
      )}
      {call.audio_deleted_at && (
        <p className="mt-1 text-xs text-slate-600">
          The audio was deleted on {formatDateTime(call.audio_deleted_at)}.
        </p>
      )}
      <div className="mt-2 flex flex-wrap items-center gap-2">
        {call.audio_available && call.status === "ready" && (
          <button
            type="button"
            className={buttonClass("secondary")}
            disabled={busy}
            onClick={listen}
          >
            Listen
          </button>
        )}
        {call.has_transcript && (
          <button
            type="button"
            className={buttonClass("secondary")}
            disabled={busy}
            aria-expanded={open}
            onClick={toggleTranscript}
          >
            {open ? "Hide transcript" : "Show transcript"}
          </button>
        )}
        {canWrite && call.audio_available && !isWorking(call) && (
          <DeleteAudioDialog
            name={call.file_name}
            closeWhen={call.audio_deleted_at}
            action={(previous) => actions.deleteAudio(call.id, previous)}
          />
        )}
      </div>
      {problem && (
        <p className="mt-2 text-sm text-red-700" role="alert">
          {problem}
        </p>
      )}
      {audio && (
        <div className="mt-2">
          <audio controls autoPlay src={audio.url} className="w-full" />
          <p className="mt-1 text-xs text-slate-600">
            {audio.which === "cleaned"
              ? "The cleaned copy (background noise reduced). The link works for one minute."
              : "The original recording. The link works for one minute."}
          </p>
        </div>
      )}
      {open && detail && <TranscriptPanel detail={detail} />}
    </li>
  );
}

export function CallsView({
  calls,
  canWrite,
  actions,
}: {
  calls: CallRecording[];
  canWrite: boolean;
  actions: CallsActions;
}) {
  const router = useRouter();
  const working = calls.some(isWorking);

  // While the worker is cleaning and transcribing, look again every few seconds.
  useEffect(() => {
    if (!working) return;
    const timer = setInterval(() => router.refresh(), REFRESH_MS);
    return () => clearInterval(timer);
  }, [working, router]);

  return (
    <div>
      {calls.length === 0 ? (
        <p className="text-sm text-slate-600">
          No call recordings yet. Add one after a call with the buyer&apos;s
          agreement; it is cleaned and written out automatically.
        </p>
      ) : (
        <ul className="divide-y divide-slate-200">
          {calls.map((call) => (
            <CallItem
              key={call.id}
              call={call}
              canWrite={canWrite}
              actions={actions}
            />
          ))}
        </ul>
      )}
      {canWrite && (
        <div className="mt-3">
          <AddCallDialog
            start={actions.start}
            finish={actions.finish}
            closeWhen={calls.map((c) => c.id).join(",")}
          />
        </div>
      )}
    </div>
  );
}
