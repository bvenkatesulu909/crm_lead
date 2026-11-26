"use client";

import { useEffect, useRef, useState } from "react";

import { buttonClass } from "@/components/ui";
import { SPEECH_LANG, type ChatLanguage } from "@/lib/public-chat";
import {
  VOICE_TEXT,
  audioBlob,
  voiceErrorText,
  type VoiceAnswer,
  type VoiceProblem,
} from "@/lib/public-voice";
import { MicError, canRecordTurn, recordTurn } from "@/lib/voice-recorder";

type Phase = "closed" | "notice" | "call" | "ended";
type Step = "listening" | "thinking" | "speaking";
type Posted = { ok: boolean; status: number; body: VoiceAnswer & VoiceProblem };

/**
 * The voice receptionist's call (ADR 0038, VR4). The visitor reads the notice and presses Start
 * (that press is the consent: the page sends the notice version with every turn); then each turn
 * is: record until the visitor stops talking -> send to our own /api/public-chat/voice route ->
 * show what was heard and the reply as text -> play the reply -> listen again. An End button is
 * always visible, and when anything goes wrong the typed chat below keeps working.
 *
 * Audio goes only to our route handler, which forwards it with the server key; no token and no
 * key is ever in this code. Everything shown is plain text.
 */
export function PublicVoiceCall({
  language,
  noticeVersion,
  onGreeting,
  onTurn,
  onSaved,
  endpoint = "/api/public-chat/voice",
  record = recordTurn,
  available = canRecordTurn,
}: {
  language: ChatLanguage;
  noticeVersion: number;
  onGreeting: (text: string) => void;
  onTurn: (heard: string, reply: string) => void;
  onSaved: () => void;
  endpoint?: string;
  /** Records one turn; replaced in tests. */
  record?: (signal: AbortSignal) => Promise<Blob | null>;
  /** Whether this browser can record at all; replaced in tests. */
  available?: () => boolean;
}) {
  const words = VOICE_TEXT[language];
  const [phase, setPhase] = useState<Phase>("closed");
  const [step, setStep] = useState<Step>("listening");
  const [message, setMessage] = useState<string | null>(null);
  const [broken, setBroken] = useState(false);
  const live = useRef(false);
  const abort = useRef<AbortController | null>(null);
  const audio = useRef<HTMLAudioElement | null>(null);
  // Read on each turn from here, so a language change cannot leave the loop on old words.
  const latest = useRef({ language, noticeVersion });
  useEffect(() => {
    latest.current = { language, noticeVersion };
  });

  // Leaving the page ends the call: the microphone and the voice stop.
  useEffect(() => () => hangUp(), []);

  function hangUp() {
    live.current = false;
    abort.current?.abort();
    audio.current?.pause();
    audio.current = null;
    if (typeof window !== "undefined" && "speechSynthesis" in window)
      window.speechSynthesis.cancel();
  }

  function speakWithBrowser(text: string) {
    if (typeof window === "undefined" || !("speechSynthesis" in window)) return;
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = SPEECH_LANG[language];
    window.speechSynthesis.cancel();
    window.speechSynthesis.speak(utterance);
  }

  function finish(text: string | null, stuck = false) {
    hangUp();
    setMessage(text);
    setBroken(stuck);
    setPhase("ended");
  }

  async function play(answer: VoiceAnswer) {
    const blob = audioBlob(answer);
    if (!blob || typeof Audio === "undefined") return;
    const url = URL.createObjectURL(blob);
    const player = new Audio(url);
    audio.current = player;
    await new Promise<void>((resolve) => {
      player.onended = () => resolve();
      player.onerror = () => resolve();
      // Some browsers return nothing from play(); a refused play must not stall the call.
      const started = player.play() as Promise<void> | undefined;
      if (started && typeof started.catch === "function")
        started.catch(() => resolve());
    });
    URL.revokeObjectURL(url);
    audio.current = null;
  }

  async function post(blob: Blob): Promise<Posted> {
    const form = new FormData();
    form.set("audio", blob, "turn.webm");
    form.set("language", latest.current.language);
    form.set("consent_version", String(latest.current.noticeVersion));
    // Bots fill every field; this one is not shown to people and is always empty here.
    form.set("website", "");
    const response = await fetch(endpoint, { method: "POST", body: form });
    const body = (await response.json().catch(() => ({}))) as VoiceAnswer &
      VoiceProblem;
    return { ok: response.ok, status: response.status, body };
  }

  async function run() {
    live.current = true;
    let quiet = 0;
    while (live.current) {
      setStep("listening");
      abort.current = new AbortController();
      let blob: Blob | null;
      try {
        blob = await record(abort.current.signal);
      } catch (error) {
        const reason = error instanceof MicError ? error.reason : "denied";
        const now = VOICE_TEXT[latest.current.language];
        finish(reason === "none" ? now.noMic : now.micDenied, true);
        return;
      }
      if (!live.current) return;
      if (!blob) {
        quiet += 1;
        const now = VOICE_TEXT[latest.current.language];
        if (quiet >= 2) {
          finish(now.heardNothing);
          return;
        }
        setMessage(now.heardNothing);
        continue;
      }
      quiet = 0;
      setMessage(null);
      setStep("thinking");
      let result: Posted;
      try {
        result = await post(blob);
      } catch {
        if (live.current)
          finish(VOICE_TEXT[latest.current.language].failed, true);
        return;
      }
      if (!live.current) return;
      if (!result.ok) {
        const problem = voiceErrorText(
          latest.current.language,
          result.status,
          result.body.code,
          result.body.detail,
        );
        // The service being off (404/503) takes the call button away for good.
        const gone = result.status === 404 || result.status === 503;
        if (problem.endsCall) {
          finish(problem.text, gone);
          return;
        }
        setMessage(problem.text);
        continue;
      }
      onTurn(result.body.heard, result.body.reply);
      if (result.body.lead_saved) onSaved();
      setStep("speaking");
      await play(result.body);
      if (!live.current) return;
      if (result.body.call_ended) {
        finish(VOICE_TEXT[latest.current.language].limitCall);
        return;
      }
    }
  }

  function start() {
    setPhase("call");
    setMessage(null);
    onGreeting(words.greeting);
    speakWithBrowser(words.greeting);
    void run();
  }

  if (broken) {
    return (
      <p
        role="status"
        className="rounded-md bg-slate-100 px-4 py-3 text-sm text-slate-700"
      >
        {message}
      </p>
    );
  }

  if (phase === "closed") {
    if (!available()) return null;
    return (
      <button
        type="button"
        onClick={() => setPhase("notice")}
        className={buttonClass("secondary")}
      >
        {words.talk}
      </button>
    );
  }

  if (phase === "notice") {
    return (
      <section
        aria-label={words.noticeTitle}
        className="rounded-md border border-slate-200 bg-white px-4 py-3 text-sm text-slate-800"
      >
        <h2 className="font-semibold">{words.noticeTitle}</h2>
        <p className="mt-1 whitespace-pre-line">{words.notice}</p>
        <div className="mt-3 flex flex-wrap gap-2">
          <button type="button" onClick={start} className={buttonClass()}>
            {words.start}
          </button>
          <button
            type="button"
            onClick={() => speakWithBrowser(words.notice)}
            className={buttonClass("secondary")}
          >
            {words.listenNotice}
          </button>
          <button
            type="button"
            onClick={() => {
              hangUp();
              setPhase("closed");
            }}
            className={buttonClass("secondary")}
          >
            {words.cancel}
          </button>
        </div>
      </section>
    );
  }

  if (phase === "ended") {
    return (
      <div className="flex flex-wrap items-center gap-3 rounded-md bg-slate-100 px-4 py-3 text-sm text-slate-700">
        <p role="status" className="flex-1">
          {message ?? words.ended}
        </p>
        <button
          type="button"
          onClick={() => {
            setMessage(null);
            setPhase("notice");
          }}
          className={buttonClass("secondary")}
        >
          {words.talk}
        </button>
      </div>
    );
  }

  return (
    <div className="flex flex-wrap items-center gap-3 rounded-md border border-brand-200 bg-brand-50 px-4 py-3 text-sm text-slate-900">
      <p role="status" aria-live="polite" className="flex-1">
        {message ??
          (step === "listening"
            ? words.listening
            : step === "thinking"
              ? words.thinking
              : words.speaking)}
      </p>
      <button
        type="button"
        onClick={() => finish(null)}
        className={buttonClass("secondary")}
      >
        {words.end}
      </button>
    </div>
  );
}
