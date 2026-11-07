"use client";

/**
 * The speech engines behind the voice conversation (ADR 0023).
 *
 * - "browser": the browser's own Web Speech API listens and `speechSynthesis` speaks. Free, but in
 *   Chrome the audio goes to Google, in Safari to Apple, in Edge to Microsoft. Firefox cannot listen.
 * - "server": the microphone is recorded here, ended by silence detection, and sent through our
 *   own route handler to the CRM's speech service (one vendor the organisation chose, or a local
 *   engine); each sentence is turned into audio there and played here.
 * - "script": a scripted engine for the browser tests only (NEXT_PUBLIC_VOICE_TEST_ENGINE=1).
 *
 * Nothing here ever sees a token: everything goes through this app's own routes.
 */

import {
  BargeInDetector,
  SilenceDetector,
  levelOf,
} from "@/lib/voice/detectors";
import type { Listener, Speaker } from "@/lib/voice/conversation";

export type EngineKind = "browser" | "server" | "script";

export class VoiceEngineError extends Error {
  constructor(public code: string) {
    super(code);
  }
}

type Recognition = {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  maxAlternatives: number;
  start(): void;
  stop(): void;
  abort(): void;
  onresult:
    | ((event: {
        results: ArrayLike<ArrayLike<{ transcript: string }>>;
      }) => void)
    | null;
  onend: (() => void) | null;
  onerror: ((event: { error?: string }) => void) | null;
};

type SpeechWindow = Window & {
  SpeechRecognition?: new () => Recognition;
  webkitSpeechRecognition?: new () => Recognition;
};

export function browserCanListen(): boolean {
  if (typeof window === "undefined") return false;
  const w = window as SpeechWindow;
  return Boolean(w.SpeechRecognition ?? w.webkitSpeechRecognition);
}

export function browserCanSpeak(): boolean {
  return typeof window !== "undefined" && "speechSynthesis" in window;
}

export function canRecord(): boolean {
  return (
    typeof window !== "undefined" &&
    typeof navigator !== "undefined" &&
    Boolean(navigator.mediaDevices?.getUserMedia) &&
    typeof MediaRecorder !== "undefined"
  );
}

/** Opens the microphone with the browser's echo cancellation (the answer must not be heard). */
export async function openMicrophone(): Promise<MediaStream> {
  try {
    return await navigator.mediaDevices.getUserMedia({
      audio: {
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      },
    });
  } catch (error) {
    const name = error instanceof DOMException ? error.name : "";
    throw new VoiceEngineError(
      name === "NotAllowedError" || name === "SecurityError"
        ? "mic_blocked"
        : "mic_unavailable",
    );
  }
}

// --- the browser's own speech ----------------------------------------------------------------

export class BrowserListener implements Listener {
  private current: Recognition | null = null;

  constructor(private lang = "en-IN") {}

  listen(): Promise<string> {
    const w = window as SpeechWindow;
    const Constructor = w.SpeechRecognition ?? w.webkitSpeechRecognition;
    if (!Constructor)
      return Promise.reject(new VoiceEngineError("cannot_listen"));
    return new Promise((resolve, reject) => {
      const recognition = new Constructor();
      this.current = recognition;
      recognition.lang = this.lang;
      recognition.continuous = false; // the browser ends the turn when the person stops talking
      recognition.interimResults = false;
      recognition.maxAlternatives = 1;
      let heard = "";
      recognition.onresult = (event) => {
        heard = Array.from(
          event.results,
          (result) => result[0]?.transcript ?? "",
        ).join(" ");
      };
      recognition.onerror = (event) => {
        // "no-speech" and "aborted" are normal: nothing was said, or we stopped it.
        if (
          event.error === "not-allowed" ||
          event.error === "service-not-allowed"
        )
          reject(new VoiceEngineError("mic_blocked"));
        else if (event.error === "network")
          reject(new VoiceEngineError("listen_network"));
      };
      recognition.onend = () => {
        this.current = null;
        resolve(heard.trim());
      };
      try {
        recognition.start();
      } catch {
        reject(new VoiceEngineError("cannot_listen"));
      }
    });
  }

  stop(): void {
    this.current?.abort();
    this.current = null;
  }
}

export class BrowserSpeaker implements Speaker {
  constructor(private lang = "en-IN") {}

  private voice(): SpeechSynthesisVoice | undefined {
    const voices = window.speechSynthesis.getVoices();
    const base = this.lang.split("-")[0];
    return (
      voices.find((v) => v.lang === this.lang) ??
      voices.find((v) => v.lang.startsWith(base) && v.localService) ??
      voices.find((v) => v.lang.startsWith(base))
    );
  }

  speak(text: string): Promise<void> {
    return new Promise((resolve) => {
      const utterance = new SpeechSynthesisUtterance(text);
      utterance.lang = this.lang;
      const voice = this.voice();
      if (voice) utterance.voice = voice;
      utterance.onend = () => resolve();
      utterance.onerror = () => resolve();
      window.speechSynthesis.speak(utterance);
      // Chrome sometimes pauses the speech queue after the tab was in the background.
      window.speechSynthesis.resume();
    });
  }

  cancel(): void {
    window.speechSynthesis.cancel();
  }
}

// --- the CRM's own speech service -------------------------------------------------------------

/** Watches a microphone stream's loudness about 20 times a second. */
function watchLevel(
  stream: MediaStream,
  onLevel: (level: number, now: number) => void,
): () => void {
  const context = new AudioContext();
  const source = context.createMediaStreamSource(stream);
  const analyser = context.createAnalyser();
  analyser.fftSize = 1024;
  source.connect(analyser);
  const samples = new Float32Array(analyser.fftSize);
  const timer = window.setInterval(() => {
    analyser.getFloatTimeDomainData(samples);
    onLevel(levelOf(samples), performance.now());
  }, 50);
  return () => {
    window.clearInterval(timer);
    source.disconnect();
    void context.close();
  };
}

export class ServerListener implements Listener {
  private finish: (() => void) | null = null;

  constructor(private stream: MediaStream) {}

  listen(): Promise<string> {
    return new Promise((resolve, reject) => {
      const chunks: Blob[] = [];
      const recorder = new MediaRecorder(this.stream);
      const detector = new SilenceDetector();
      let spoke = false;
      let cancelled = false;
      const unwatch = watchLevel(this.stream, (level, now) => {
        const verdict = detector.feed(level, now);
        if (verdict === "speaking") spoke = true;
        if (
          (verdict === "ended" || verdict === "nothing") &&
          recorder.state === "recording"
        )
          recorder.stop();
      });
      this.finish = () => {
        cancelled = true;
        if (recorder.state === "recording") recorder.stop();
      };
      recorder.ondataavailable = (event) => {
        if (event.data.size) chunks.push(event.data);
      };
      recorder.onstop = async () => {
        unwatch();
        this.finish = null;
        if (cancelled || !spoke || !chunks.length) return resolve("");
        const blob = new Blob(chunks, {
          type: recorder.mimeType || "audio/webm",
        });
        const form = new FormData();
        form.append(
          "file",
          blob,
          blob.type.includes("mp4") ? "speech.mp4" : "speech.webm",
        );
        try {
          const response = await fetch("/api/voice/transcribe", {
            method: "POST",
            body: form,
          });
          if (!response.ok) {
            const problem = (await response.json().catch(() => ({}))) as {
              code?: string;
            };
            return reject(
              new VoiceEngineError(problem.code ?? "voice_unavailable"),
            );
          }
          resolve(
            String(
              ((await response.json()) as { text?: string }).text ?? "",
            ).trim(),
          );
        } catch {
          reject(new VoiceEngineError("voice_unavailable"));
        }
      };
      recorder.start(250);
    });
  }

  stop(): void {
    this.finish?.();
  }
}

export class ServerSpeaker implements Speaker {
  private audio: HTMLAudioElement | null = null;
  private ready = new Map<string, Promise<string | null>>();
  private urls: string[] = [];
  private finishCurrent: (() => void) | null = null;

  /** Fetches the next sentence's audio while the current one is still playing. */
  prepare(text: string): void {
    if (this.ready.has(text)) return;
    this.ready.set(
      text,
      fetch("/api/voice/speak", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
      })
        .then(async (response) => {
          if (!response.ok) return null;
          const url = URL.createObjectURL(await response.blob());
          this.urls.push(url);
          return url;
        })
        .catch(() => null),
    );
  }

  async speak(text: string): Promise<void> {
    this.prepare(text);
    const url = await this.ready.get(text);
    this.ready.delete(text);
    if (!url) return; // could not be turned into audio: it is still on the screen
    await new Promise<void>((resolve) => {
      const audio = new Audio(url);
      this.audio = audio;
      this.finishCurrent = resolve;
      audio.onended = () => resolve();
      audio.onerror = () => resolve();
      audio.play().catch(() => resolve());
    });
    this.audio = null;
    this.finishCurrent = null;
  }

  cancel(): void {
    this.audio?.pause();
    this.audio = null;
    this.finishCurrent?.();
    this.finishCurrent = null;
    this.ready.clear();
    for (const url of this.urls.splice(0)) URL.revokeObjectURL(url);
  }
}

// --- interrupting ---------------------------------------------------------------------------------

/** Calls `onSpeech` once when the person starts talking while the assistant speaks. */
export function watchForBargeIn(
  stream: MediaStream,
  onSpeech: () => void,
): () => void {
  const detector = new BargeInDetector();
  let fired = false;
  return watchLevel(stream, (level, now) => {
    if (!fired && detector.feed(level, now)) {
      fired = true;
      onSpeech();
    }
  });
}

// --- the scripted engine for browser tests -------------------------------------------------------

type ScriptWindow = Window & {
  __crmVoiceScript?: string[];
  __crmVoiceSpoken?: string[];
};

export function scriptEngineOn(): boolean {
  return process.env.NEXT_PUBLIC_VOICE_TEST_ENGINE === "1";
}

export class ScriptListener implements Listener {
  private wake: (() => void) | null = null;

  async listen(): Promise<string> {
    const w = window as ScriptWindow;
    await new Promise<void>((resolve) => {
      this.wake = resolve;
      window.setTimeout(resolve, 200);
    });
    return w.__crmVoiceScript?.shift() ?? "";
  }

  stop(): void {
    this.wake?.();
  }
}

export class ScriptSpeaker implements Speaker {
  async speak(text: string): Promise<void> {
    const w = window as ScriptWindow;
    (w.__crmVoiceSpoken ??= []).push(text);
    await new Promise((resolve) => window.setTimeout(resolve, 20));
  }

  cancel(): void {}
}
