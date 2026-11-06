/**
 * The voice conversation loop (ADR 0023): listen -> send -> speak each sentence -> listen again.
 *
 * It knows nothing about microphones or speakers: it is given a Listener and a Speaker (the
 * browser's own speech, the server's speech service, or a script in tests) and the function that
 * asks the assistant. So the whole loop - stopping, interrupting, errors - is tested without a
 * browser.
 *
 * Rules it keeps:
 * - it never listens while it speaks (the microphone would hear the answer);
 * - each sentence is spoken as soon as it arrives; the next question waits until the previous
 *   answer has finished on the server (turns are remembered in order);
 * - an interruption only stops the SPEAKING - the answer still finishes and is remembered;
 * - it stops after two turns in a row in which nothing was heard.
 */

import type {
  StreamDone,
  StreamEvent,
  StreamProposal,
} from "@/lib/assistant-stream";

export interface Listener {
  /** Listen for one question; resolves with what was heard ("" for nothing). */
  listen(): Promise<string>;
  /** Stop listening now (the promise resolves with what was heard so far, or ""). */
  stop(): void;
}

export interface Speaker {
  speak(text: string): Promise<void>;
  /** Stop speaking now and forget what was waiting. */
  cancel(): void;
  /** Optional: start getting a sentence ready (e.g. download its audio) before its turn. */
  prepare?(text: string): void;
}

export type Ask = (
  question: string,
  onEvent: (event: StreamEvent) => void,
) => Promise<StreamDone>;

export type VoiceState = "idle" | "listening" | "thinking" | "speaking";

export type VoiceTurn = {
  role: "user" | "assistant";
  text: string;
  proposals?: StreamProposal[];
  final?: boolean;
};

export const WORKING_PHRASE = "One moment, I'm looking that up.";
export const NOTHING_HEARD =
  "I didn't hear anything, so I stopped listening. Press Start to talk again.";

export type Callbacks = {
  onState(state: VoiceState): void;
  onTurns(turns: VoiceTurn[]): void;
  onError(code: string, detail?: string): void;
};

/** Speaks sentences one after another, in the order they arrive. */
export class SpeechQueue {
  private queue: string[] = [];
  private running: Promise<void> | null = null;
  private muted = false;

  constructor(
    private speaker: Speaker,
    private onStart: () => void,
  ) {}

  add(text: string): void {
    if (this.muted || !text.trim()) return;
    this.speaker.prepare?.(text);
    this.queue.push(text);
    this.running ??= this.drain();
  }

  private async drain(): Promise<void> {
    while (this.queue.length && !this.muted) {
      const next = this.queue.shift() as string;
      this.onStart();
      try {
        await this.speaker.speak(next);
      } catch {
        // A sentence that could not be spoken is skipped; it is still on the screen.
      }
    }
    this.running = null;
  }

  /** Waits until everything queued so far has been spoken (or the queue was muted). */
  async idle(): Promise<void> {
    while (this.running) await this.running;
  }

  mute(): void {
    this.muted = true;
    this.queue = [];
    this.speaker.cancel();
  }
}

export class VoiceConversation {
  private running = false;
  private turns: VoiceTurn[] = [];
  private queue: SpeechQueue | null = null;
  private pending: Promise<unknown> | null = null;
  private interruptTurn: (() => void) | null = null;

  constructor(
    private listener: Listener,
    private speaker: Speaker,
    private ask: Ask,
    private callbacks: Callbacks,
  ) {}

  get active(): boolean {
    return this.running;
  }

  async start(): Promise<void> {
    if (this.running) return;
    this.running = true;
    let silent = 0;
    try {
      while (this.running) {
        this.callbacks.onState("listening");
        const heard = (await this.listener.listen()).trim();
        if (!this.running) break;
        if (!heard) {
          silent += 1;
          if (silent >= 2) {
            this.callbacks.onError("nothing_heard", NOTHING_HEARD);
            break;
          }
          continue;
        }
        silent = 0;
        // The previous answer must be finished (and remembered) before the next question.
        if (this.pending) await this.pending.catch(() => undefined);
        if (!this.running) break;
        const ok = await this.turn(heard);
        if (!ok) break;
      }
    } finally {
      this.running = false;
      this.callbacks.onState("idle");
    }
  }

  /** One question and its spoken answer. Resolves false when the conversation must stop. */
  private async turn(question: string): Promise<boolean> {
    this.push({ role: "user", text: question, final: true });
    const answer: VoiceTurn = { role: "assistant", text: "" };
    this.push(answer);
    this.callbacks.onState("thinking");
    const queue = new SpeechQueue(this.speaker, () => {
      if (this.running) this.callbacks.onState("speaking");
    });
    this.queue = queue;
    let saidWorking = false;
    let interrupted = false;
    const interruption = new Promise<"interrupted">((resolve) => {
      this.interruptTurn = () => {
        interrupted = true;
        resolve("interrupted");
      };
    });
    const finished = this.ask(question, (event) => {
      if (event.type === "sentence") {
        answer.text = answer.text ? `${answer.text} ${event.text}` : event.text;
        this.publish();
        queue.add(event.text);
      } else if (event.type === "working" && !saidWorking) {
        saidWorking = true;
        queue.add(WORKING_PHRASE);
      }
    }).then(
      (done) => {
        answer.text = done.answer;
        answer.proposals = done.proposals;
        answer.final = true;
        this.publish();
        return true;
      },
      (error: unknown) => {
        queue.mute();
        this.turns = this.turns.filter((t) => t !== answer);
        this.publish();
        const code =
          (error as { code?: string }).code ?? "assistant_unavailable";
        this.callbacks.onError(code, (error as { detail?: string }).detail);
        // Interrupted earlier, the loop is already listening again: end the conversation.
        if (interrupted) this.stop();
        return false;
      },
    );
    this.pending = finished;
    void finished.finally(() => {
      if (this.pending === finished) this.pending = null;
    });
    if ((await Promise.race([finished, interruption])) === "interrupted")
      return this.running;
    if (!(await finished)) return false;
    await Promise.race([queue.idle(), interruption]);
    if (this.queue === queue) this.queue = null;
    return this.running;
  }

  /** Stop speaking now and listen again; the answer still finishes and is remembered. */
  interrupt(): void {
    this.queue?.mute();
    this.interruptTurn?.();
  }

  /** End the conversation: stop listening and speaking. */
  stop(): void {
    this.running = false;
    this.listener.stop();
    this.queue?.mute();
    this.speaker.cancel();
  }

  private push(turn: VoiceTurn): void {
    this.turns = [...this.turns, turn];
    this.publish();
  }

  private publish(): void {
    this.callbacks.onTurns(this.turns.map((t) => ({ ...t })));
  }
}
