/**
 * Hearing when a person starts and stops talking, from the microphone's loudness (ADR 0023, VM4).
 *
 * Both detectors are plain arithmetic over (level, time) samples, so they can be tested without a
 * microphone. The page feeds them about 20 samples a second from a Web Audio analyser; `level` is
 * the loudness between 0 (silence) and 1 (very loud).
 */

export type SilenceOptions = {
  /** Silence after speech that ends the turn. */
  endAfterMs: number;
  /** No speech at all for this long: give up and report "nothing heard". */
  noSpeechMs: number;
  /** A turn never records longer than this. */
  maxMs: number;
};

export const SILENCE_DEFAULTS: SilenceOptions = {
  endAfterMs: 800,
  noSpeechMs: 8000,
  maxMs: 30000,
};

export type SilenceVerdict = "waiting" | "speaking" | "ended" | "nothing";

/**
 * Ends a recording when the person stops talking. The threshold adapts to the room: it starts a
 * little above the quietest level heard so far, so a fan or traffic is not taken for speech.
 */
export class SilenceDetector {
  private started: number | null = null;
  private spokeAt: number | null = null;
  private lastLoud = 0;
  private floor = 1;

  constructor(private options: SilenceOptions = SILENCE_DEFAULTS) {}

  threshold(): number {
    return Math.max(0.04, Math.min(0.5, this.floor * 2.5 + 0.02));
  }

  feed(level: number, now: number): SilenceVerdict {
    if (this.started === null) this.started = now;
    this.floor = Math.min(this.floor, level);
    if (level >= this.threshold()) {
      this.spokeAt ??= now;
      this.lastLoud = now;
    }
    if (now - this.started >= this.options.maxMs)
      return this.spokeAt === null ? "nothing" : "ended";
    if (this.spokeAt === null)
      return now - this.started >= this.options.noSpeechMs
        ? "nothing"
        : "waiting";
    return now - this.lastLoud >= this.options.endAfterMs
      ? "ended"
      : "speaking";
  }
}

/**
 * Notices a person talking WHILE the assistant speaks ("barge-in"). It needs the loudness to stay
 * above the threshold for `holdMs` in a row, so a cough or the assistant's own voice leaking
 * into the microphone (the browser's echo cancellation removes most of it) does not cut it off.
 */
export class BargeInDetector {
  private loudSince: number | null = null;

  constructor(
    private threshold = 0.12,
    private holdMs = 300,
  ) {}

  feed(level: number, now: number): boolean {
    if (level < this.threshold) {
      this.loudSince = null;
      return false;
    }
    this.loudSince ??= now;
    return now - this.loudSince >= this.holdMs;
  }

  reset(): void {
    this.loudSince = null;
  }
}

/** The loudness (0..1) of one frame of microphone samples, as root mean square. */
export function levelOf(samples: ArrayLike<number>): number {
  if (!samples.length) return 0;
  let sum = 0;
  for (let i = 0; i < samples.length; i++) sum += samples[i] * samples[i];
  return Math.min(1, Math.sqrt(sum / samples.length) * 4);
}
