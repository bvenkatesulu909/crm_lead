"use client";

import { useEffect, useRef, useState, useSyncExternalStore } from "react";

import {
  createRecognition,
  speechRecognitionAvailable,
  type SpeechRecognitionLike,
} from "@/lib/speech";

/** Dictate into a textarea. Browser speech-to-text; audio never reaches CRM-Lead. */
export function DictationButton({
  onTranscript,
  label = "Dictate",
}: {
  onTranscript: (text: string) => void;
  label?: string;
}) {
  const [listening, setListening] = useState(false);
  const recognition = useRef<SpeechRecognitionLike | null>(null);
  const available = useSyncExternalStore(
    () => () => {},
    speechRecognitionAvailable,
    () => false,
  );

  useEffect(() => () => recognition.current?.stop(), []);

  if (!available) return null;

  function toggle() {
    if (listening) {
      recognition.current?.stop();
      setListening(false);
      return;
    }
    const instance = createRecognition();
    if (!instance) return;
    instance.lang = "en-US";
    instance.continuous = false;
    instance.interimResults = false;
    instance.onresult = (event) => {
      const transcript = Array.from(
        { length: event.results.length },
        (_, index) => event.results[index][0].transcript,
      ).join(" ");
      if (transcript) onTranscript(transcript);
    };
    instance.onend = () => setListening(false);
    instance.onerror = () => setListening(false);
    recognition.current = instance;
    setListening(true);
    instance.start();
  }

  return (
    <button
      type="button"
      onClick={toggle}
      aria-pressed={listening}
      className="mt-2 rounded-md bg-white px-2.5 py-1 text-xs font-medium text-slate-700 ring-1 ring-inset ring-slate-300 hover:bg-slate-50"
    >
      {listening ? "Listening…" : label}
    </button>
  );
}
