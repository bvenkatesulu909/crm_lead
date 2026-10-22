"use client";

import { useEffect, useRef, useState } from "react";
import { createRecognition, type SpeechRecognitionLike } from "@/lib/speech";

type State = "idle" | "permission" | "recording" | "uploading" | "done" | "error";
const MAX_MS = 60000;

export function VoiceRecorder({ onTranscript, onComplete, label = "Speak" }: { onTranscript: (text: string) => void; onComplete?: () => void; label?: string }) {
  const [state, setState] = useState<State>("idle");
  const [consented, setConsented] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [seconds, setSeconds] = useState(0);
  const recorder = useRef<MediaRecorder | null>(null);
  const stream = useRef<MediaStream | null>(null);
  const chunks = useRef<Blob[]>([]);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);
  const recognition = useRef<SpeechRecognitionLike | null>(null);

  useEffect(() => {
    return () => { if (timer.current) clearInterval(timer.current); stream.current?.getTracks().forEach((t) => t.stop()); recognition.current?.stop(); };
  }, []);

  function micError(error: unknown): string {
    const name = error instanceof DOMException ? error.name : "";
    if (name === "NotAllowedError" || name === "SecurityError")
      return "Microphone permission is blocked. Allow this exact origin in Chrome and in Windows microphone privacy settings.";
    if (name === "NotFoundError" || name === "DevicesNotFoundError")
      return "No microphone was found. Connect or select an input device.";
    if (name === "NotReadableError" || name === "TrackStartError")
      return "The microphone is busy in another app. Close Teams/Zoom and retry.";
    if (name === "OverconstrainedError") return "The selected microphone does not support the requested audio settings.";
    if (name) return "Microphone error: " + name + ". Check Windows privacy and the input device.";
    return "Microphone permission was denied or no microphone is available.";
  }

  function cleanup() { if (timer.current) clearInterval(timer.current); timer.current = null; stream.current?.getTracks().forEach((t) => t.stop()); stream.current = null; setSeconds(0); }

  function fallback() {
    const instance = createRecognition();
    if (!instance) { setState("error"); setError("Microphone transcription is unavailable in this browser."); return; }
    recognition.current = instance; instance.lang = "en-US"; instance.continuous = false; instance.interimResults = false;
    instance.onresult = (event) => { const text = Array.from({ length: event.results.length }, (_, i) => event.results[i][0].transcript).join(" "); if (text) { onTranscript(text); setState("done"); onComplete?.(); } };
    instance.onend = () => setState((s) => s === "error" ? s : "done");
    instance.onerror = () => { setState("error"); setError("Speech recognition failed. Please type instead."); };
    setState("recording"); instance.start();
  }

  async function upload(blob: Blob) {
    setState("uploading");
    const form = new FormData(); form.append("file", blob, "speech.webm");
    try {
      const response = await fetch("/api/voice/transcribe", { method: "POST", body: form });
      if (response.status === 503 || response.status === 501) return fallback();
      if (!response.ok) throw new Error("failed");
      const data = (await response.json()) as { text?: string };
      const text = (data.text ?? "").trim(); if (!text) throw new Error("empty");
      onTranscript(text); setState("done");
      onComplete?.();
    } catch { fallback(); }
  }

  async function start() {
    setError(null); setState("permission");
    try {
      const media = await navigator.mediaDevices.getUserMedia({ audio: true }); stream.current = media; chunks.current = [];
      const instance = new MediaRecorder(media); recorder.current = instance;
      instance.ondataavailable = (e) => { if (e.data.size) chunks.current.push(e.data); };
      instance.onstop = () => { cleanup(); const blob = new Blob(chunks.current, { type: "audio/webm" }); if (blob.size) void upload(blob); else setState("idle"); };
      instance.start(); setState("recording"); setSeconds(0);
      timer.current = setInterval(() => setSeconds((v) => { if (v + 1 >= MAX_MS / 1000) { instance.stop(); return MAX_MS / 1000; } return v + 1; }), 1000);
    } catch (error) { setState("error"); setError(micError(error)); }
  }

  function stop() { if (timer.current) clearInterval(timer.current); if (recorder.current?.state === "recording") recorder.current.stop(); else if (recognition.current) { recognition.current.stop(); setState("idle"); } }
  function cancel() { recognition.current?.stop(); if (recorder.current?.state === "recording") { recorder.current.onstop = null; recorder.current.stop(); } cleanup(); setState("idle"); setError(null); }

  if (!consented) return (
    <div className="rounded-md bg-slate-50 p-2 text-xs text-slate-700">
      <p>Voice is converted to text to answer you. Audio is processed by the speech service and not stored.</p>
      <button type="button" onClick={() => { localStorage.setItem("crm-voice-consent", "yes"); setConsented(true); void start(); }} className="mt-2 rounded-md bg-brand-600 px-3 py-1.5 text-white">Allow microphone</button>
    </div>
  );

  return (
    <div className="flex flex-wrap items-center gap-2">
      {state === "recording" && <span aria-live="polite" className="text-sm font-medium text-red-700">Recording {seconds}s / 60s</span>}
      {state === "permission" && <span className="text-sm text-slate-600">Waiting for microphone…</span>}
      {state === "uploading" && <span className="text-sm text-slate-600">Transcribing…</span>}
      {state === "recording" ? (<>
        <button type="button" onClick={stop} className="rounded-md bg-white px-3 py-2 text-sm ring-1 ring-inset ring-slate-300">Stop</button>
        <button type="button" onClick={cancel} className="rounded-md bg-white px-3 py-2 text-sm ring-1 ring-inset ring-slate-300">Cancel</button>
      </>) : state === "error" ? (
        <button type="button" onClick={() => void start()} className="rounded-md bg-white px-3 py-2 text-sm ring-1 ring-inset ring-slate-300">Retry</button>
      ) : (
        <button type="button" disabled={state === "uploading"} onClick={() => void start()} className="rounded-md bg-white px-3 py-2 text-sm font-medium text-slate-700 ring-1 ring-inset ring-slate-300">Mic {label}</button>
      )}
      {error && <span role="alert" className="text-xs text-red-700">{error}</span>}
    </div>
  );
}