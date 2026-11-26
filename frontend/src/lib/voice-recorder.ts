"use client";

import { VAD, createVad } from "@/lib/public-voice";

/** Why a turn could not be recorded: the visitor said no, or there is no microphone. */
export class MicError extends Error {
  constructor(readonly reason: "denied" | "none") {
    super(reason);
  }
}

const MIME_CHOICES = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"];

function pickMime(): string | undefined {
  if (typeof MediaRecorder === "undefined") return undefined;
  return MIME_CHOICES.find((type) => MediaRecorder.isTypeSupported(type));
}

/** Whether this browser can record a turn at all (the page shows the button only then). */
export function canRecordTurn(): boolean {
  return (
    typeof navigator !== "undefined" &&
    !!navigator.mediaDevices?.getUserMedia &&
    typeof MediaRecorder !== "undefined"
  );
}

/**
 * Records ONE spoken turn: starts when called, stops by itself when the visitor stops talking
 * (see createVad), and gives the audio back - or null when nothing was said or the call was
 * ended. The microphone is always released. Nothing leaves the browser from here.
 */
export async function recordTurn(signal: AbortSignal): Promise<Blob | null> {
  let stream: MediaStream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  } catch (error) {
    const name = (error as { name?: string }).name;
    throw new MicError(
      name === "NotFoundError" || name === "OverconstrainedError"
        ? "none"
        : "denied",
    );
  }
  const mime = pickMime();
  const recorder = new MediaRecorder(stream, mime ? { mimeType: mime } : {});
  const chunks: Blob[] = [];
  recorder.ondataavailable = (event) => {
    if (event.data.size > 0) chunks.push(event.data);
  };
  const context = new AudioContext();
  const analyser = context.createAnalyser();
  analyser.fftSize = 1024;
  context.createMediaStreamSource(stream).connect(analyser);
  const samples = new Uint8Array(analyser.fftSize);
  const vad = createVad(VAD);

  return await new Promise<Blob | null>((resolve) => {
    let discard = false;
    const finish = () => {
      clearInterval(timer);
      signal.removeEventListener("abort", onAbort);
      stream.getTracks().forEach((track) => track.stop());
      void context.close();
    };
    recorder.onstop = () => {
      finish();
      resolve(
        discard || chunks.length === 0
          ? null
          : new Blob(chunks, { type: recorder.mimeType || "audio/webm" }),
      );
    };
    const stop = (throwAway: boolean) => {
      discard = throwAway;
      if (recorder.state !== "inactive") recorder.stop();
    };
    const onAbort = () => stop(true);
    signal.addEventListener("abort", onAbort);
    const timer = setInterval(() => {
      analyser.getByteTimeDomainData(samples);
      let sum = 0;
      for (const value of samples) sum += ((value - 128) / 128) ** 2;
      const verdict = vad.push(Math.sqrt(sum / samples.length), Date.now());
      if (verdict === "stop") stop(false);
      if (verdict === "nothing") stop(true);
    }, 100);
    recorder.start();
  });
}
