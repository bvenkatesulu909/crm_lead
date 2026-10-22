"use client";

import { useEffect, useRef, useState } from "react";

type State = "idle" | "loading" | "playing";

/** Server TTS with play/stop/replay; falls back to browser speech on 503. */
export function SpeakButton({ text }: { text: string }) {
  const [state, setState] = useState<State>("idle");
  const audio = useRef<HTMLAudioElement | null>(null);
  const url = useRef<string | null>(null);

  useEffect(() => () => {
    audio.current?.pause();
    if (url.current) URL.revokeObjectURL(url.current);
    window.speechSynthesis?.cancel();
  }, []);

  function stop() {
    audio.current?.pause();
    if (audio.current) audio.current.currentTime = 0;
    setState("idle");
  }

  function browserSpeak() {
    if (!("speechSynthesis" in window)) return;
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.onend = () => setState("idle");
    utterance.onerror = () => setState("idle");
    window.speechSynthesis.cancel();
    window.speechSynthesis.speak(utterance);
    setState("playing");
  }

  async function play() {
    setState("loading");
    try {
      const response = await fetch("/api/voice/speak", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
      });
      if (response.status === 503 || response.status === 501) {
        browserSpeak();
        return;
      }
      if (!response.ok) throw new Error("tts failed");
      const blob = await response.blob();
      if (url.current) URL.revokeObjectURL(url.current);
      url.current = URL.createObjectURL(blob);
      const instance = new Audio(url.current);
      audio.current = instance;
      instance.onended = () => setState("idle");
      instance.onerror = () => setState("idle");
      await instance.play();
      setState("playing");
    } catch {
      browserSpeak();
    }
  }

  function replay() {
    if (audio.current && url.current) {
      audio.current.currentTime = 0;
      void audio.current.play();
      setState("playing");
    } else {
      browserSpeak();
    }
  }

  if (state === "playing") {
    return (
      <span className="mt-2 inline-flex gap-2">
        <button type="button" onClick={stop} className="rounded-md bg-white px-2 py-1 text-[11px] ring-1 ring-inset ring-slate-300">Stop</button>
        <button type="button" onClick={replay} className="rounded-md bg-white px-2 py-1 text-[11px] ring-1 ring-inset ring-slate-300">Replay</button>
      </span>
    );
  }

  return (
    <button
      type="button"
      onClick={() => void play()}
      disabled={state === "loading"}
      className="mt-2 rounded-md bg-white px-2 py-1 text-[11px] font-medium text-slate-700 ring-1 ring-inset ring-slate-300 hover:bg-slate-50"
      aria-label="Listen to the answer"
    >
      {state === "loading" ? "Loading audio…" : "Listen"}
    </button>
  );
}
