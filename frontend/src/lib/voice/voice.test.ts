import { describe, expect, it, vi } from "vitest";

import {
  EventParser,
  errorMessage,
  type StreamDone,
  type StreamEvent,
} from "@/lib/assistant-stream";
import {
  chooseEngine,
  privacyText,
  unavailableText,
  type VoiceStatus,
} from "@/lib/voice/choose";
import {
  NOTHING_HEARD,
  SpeechQueue,
  VoiceConversation,
  WORKING_PHRASE,
  type Ask,
  type Listener,
  type Speaker,
  type VoiceState,
  type VoiceTurn,
} from "@/lib/voice/conversation";
import {
  BargeInDetector,
  SilenceDetector,
  levelOf,
} from "@/lib/voice/detectors";

const tick = () => new Promise((resolve) => setTimeout(resolve, 0));

describe("reading the streamed answer", () => {
  it("parses events split across chunks", () => {
    const parser = new EventParser();
    expect(parser.push('event: sentence\ndata: {"text":"Hel')).toEqual([]);
    expect(parser.push('lo."}\n\nevent: working\ndata: {}\n\n')).toEqual([
      { type: "sentence", text: "Hello." },
      { type: "working" },
    ]);
  });

  it("reads done and error events, and Windows line endings", () => {
    const parser = new EventParser();
    const events = parser.push(
      'event: done\r\ndata: {"answer":"Hi.","ticket_id":"t","links":["/leads/1"],"proposals":[]}\r\n\r\n' +
        'event: error\ndata: {"code":"agent_unavailable","detail":"off"}\n\n',
    );
    expect(events[0]).toEqual({
      type: "done",
      done: {
        answer: "Hi.",
        ticket_id: "t",
        links: ["/leads/1"],
        proposals: [],
      },
    });
    expect(events[1]).toEqual({
      type: "error",
      code: "agent_unavailable",
      detail: "off",
    });
  });

  it("ignores broken and unknown events", () => {
    const parser = new EventParser();
    expect(
      parser.push(
        "event: sentence\ndata: {not json\n\nevent: ping\ndata: {}\n\n",
      ),
    ).toEqual([]);
  });

  it("explains error codes in plain words", () => {
    expect(errorMessage("agent_budget_reached")).toMatch(/allowance/);
    expect(errorMessage("weird", "Server said so.")).toBe("Server said so.");
  });
});

describe("hearing when a person stops talking", () => {
  it("ends after speech followed by silence", () => {
    const detector = new SilenceDetector({
      endAfterMs: 800,
      noSpeechMs: 8000,
      maxMs: 30000,
    });
    expect(detector.feed(0.01, 0)).toBe("waiting");
    expect(detector.feed(0.3, 100)).toBe("speaking");
    expect(detector.feed(0.25, 500)).toBe("speaking");
    expect(detector.feed(0.01, 900)).toBe("speaking");
    expect(detector.feed(0.01, 1400)).toBe("ended");
  });

  it("gives up when nobody speaks", () => {
    const detector = new SilenceDetector({
      endAfterMs: 800,
      noSpeechMs: 2000,
      maxMs: 30000,
    });
    expect(detector.feed(0.01, 0)).toBe("waiting");
    expect(detector.feed(0.015, 2100)).toBe("nothing");
  });

  it("does not take a steady background noise for speech", () => {
    const detector = new SilenceDetector({
      endAfterMs: 800,
      noSpeechMs: 3000,
      maxMs: 30000,
    });
    for (let t = 0; t < 3000; t += 50)
      expect(detector.feed(0.03, t)).toBe("waiting");
    expect(detector.feed(0.03, 3000)).toBe("nothing");
  });

  it("never records longer than the maximum", () => {
    const detector = new SilenceDetector({
      endAfterMs: 800,
      noSpeechMs: 8000,
      maxMs: 1000,
    });
    detector.feed(0.01, 0);
    detector.feed(0.4, 100);
    expect(detector.feed(0.4, 1000)).toBe("ended");
  });

  it("notices a person talking over the assistant only when it lasts", () => {
    const barge = new BargeInDetector(0.12, 300);
    expect(barge.feed(0.5, 0)).toBe(false);
    expect(barge.feed(0.05, 100)).toBe(false); // a cough: reset
    expect(barge.feed(0.5, 200)).toBe(false);
    expect(barge.feed(0.5, 400)).toBe(false);
    expect(barge.feed(0.5, 500)).toBe(true);
  });

  it("measures loudness", () => {
    expect(levelOf([])).toBe(0);
    expect(levelOf([0, 0, 0])).toBe(0);
    expect(levelOf([0.1, -0.1, 0.1, -0.1])).toBeCloseTo(0.4);
  });
});

describe("choosing the speech engine", () => {
  const status = (over: Partial<VoiceStatus> = {}): VoiceStatus => ({
    enabled: true,
    browser_engine: true,
    server_engine: false,
    minutes_used: 0,
    minutes_budget: 300,
    ...over,
  });
  const caps = {
    canListen: true,
    canSpeak: true,
    canRecord: true,
    script: false,
  };

  it("offers nothing while voice is switched off", () => {
    expect(chooseEngine(status({ enabled: false }), caps)).toEqual({
      kind: "none",
      reason: "off",
    });
    expect(chooseEngine(null, caps)).toEqual({ kind: "none", reason: "off" });
  });

  it("prefers the CRM's speech service when it is set up", () => {
    expect(chooseEngine(status({ server_engine: true }), caps)).toEqual({
      kind: "server",
    });
  });

  it("uses the browser's speech otherwise", () => {
    expect(chooseEngine(status(), caps)).toEqual({ kind: "browser" });
  });

  it("never uses the browser's speech when the organisation forbids it", () => {
    expect(chooseEngine(status({ browser_engine: false }), caps)).toEqual({
      kind: "none",
      reason: "needs_server",
    });
  });

  it("says so when the browser cannot listen (Firefox)", () => {
    const choice = chooseEngine(status(), { ...caps, canListen: false });
    expect(choice).toEqual({ kind: "none", reason: "browser_cannot_listen" });
    expect(unavailableText("browser_cannot_listen")).toMatch(/Firefox/);
  });

  it("names who hears the audio for each engine", () => {
    expect(privacyText("browser")).toMatch(
      /Google in Chrome, Apple in Safari, Microsoft in Edge/,
    );
    expect(privacyText("server")).toMatch(/does not store the audio/);
  });
});

// --- the loop -------------------------------------------------------------------------------------

class ScriptedListener implements Listener {
  calls = 0;
  stopped = false;
  constructor(
    private heard: string[],
    private log: string[],
  ) {}
  async listen(): Promise<string> {
    this.calls += 1;
    this.log.push("listen");
    await tick();
    return this.heard.shift() ?? "";
  }
  stop(): void {
    this.stopped = true;
  }
}

class RecordingSpeaker implements Speaker {
  spoken: string[] = [];
  cancelled = 0;
  private release: (() => void) | null = null;
  constructor(
    private log: string[],
    private hold = false,
  ) {}
  async speak(text: string): Promise<void> {
    this.log.push(`speak:${text}`);
    this.spoken.push(text);
    if (this.hold)
      await new Promise<void>((resolve) => (this.release = resolve));
    else await tick();
  }
  cancel(): void {
    this.cancelled += 1;
    this.release?.();
  }
  finishSpeaking(): void {
    this.release?.();
  }
}

function done(answer: string, extra: Partial<StreamDone> = {}): StreamDone {
  return { answer, ticket_id: "t", links: [], proposals: [], ...extra };
}

function scriptedAsk(
  answers: Record<string, StreamEvent[]>,
  log: string[],
  gate?: Promise<void>,
): Ask {
  return async (question, onEvent) => {
    log.push(`ask:${question}`);
    const events = answers[question] ?? [];
    for (const event of events) {
      if (event.type === "done") {
        if (gate) await gate;
        return event.done;
      }
      if (event.type === "error")
        throw Object.assign(new Error(event.code), { code: event.code });
      onEvent(event);
      await tick();
    }
    return done("");
  };
}

function callbacks() {
  const states: VoiceState[] = [];
  const errors: string[] = [];
  let turns: VoiceTurn[] = [];
  return {
    states,
    errors,
    turns: () => turns,
    cb: {
      onState: (s: VoiceState) => states.push(s),
      onTurns: (t: VoiceTurn[]) => (turns = t),
      onError: (code: string) => errors.push(code),
    },
  };
}

describe("the voice conversation loop", () => {
  it("speaks each sentence as it arrives, then listens again", async () => {
    const log: string[] = [];
    const listener = new ScriptedListener(["Which tickets are open?"], log);
    const speaker = new RecordingSpeaker(log);
    const ask = scriptedAsk(
      {
        "Which tickets are open?": [
          { type: "sentence", text: "Two are open." },
          { type: "sentence", text: "One is urgent." },
          { type: "done", done: done("Two are open. One is urgent.") },
        ],
      },
      log,
    );
    const c = callbacks();
    await new VoiceConversation(listener, speaker, ask, c.cb).start();
    expect(speaker.spoken).toEqual(["Two are open.", "One is urgent."]);
    // The first sentence is spoken before the answer has finished.
    expect(log.indexOf("speak:Two are open.")).toBeLessThan(
      log.lastIndexOf("listen"),
    );
    expect(c.turns().map((t) => [t.role, t.text])).toEqual([
      ["user", "Which tickets are open?"],
      ["assistant", "Two are open. One is urgent."],
    ]);
    // It never listens while it speaks: every "listen" comes after the speaking of the turn.
    const lastSpeak = log.lastIndexOf("speak:One is urgent.");
    expect(
      log
        .slice(log.indexOf("speak:Two are open."), lastSpeak)
        .includes("listen"),
    ).toBe(false);
    expect(c.states).toEqual(
      expect.arrayContaining(["listening", "thinking", "speaking", "idle"]),
    );
  });

  it("does not listen again until the answer has been spoken", async () => {
    const log: string[] = [];
    const speaker = new RecordingSpeaker(log, true);
    const listener = new ScriptedListener(["q"], log);
    const ask = scriptedAsk(
      {
        q: [
          { type: "sentence", text: "Still talking." },
          { type: "done", done: done("Still talking.") },
        ],
      },
      log,
    );
    const loop = new VoiceConversation(listener, speaker, ask, callbacks().cb);
    const running = loop.start();
    while (!speaker.spoken.length) await tick();
    for (let i = 0; i < 10; i++) await tick();
    expect(listener.calls).toBe(1); // the answer is done, but it is still being spoken
    speaker.finishSpeaking();
    while (listener.calls < 2) await tick();
    loop.stop();
    await running;
  });

  it("says one fixed sentence while tools run", async () => {
    const log: string[] = [];
    const speaker = new RecordingSpeaker(log);
    const ask = scriptedAsk(
      {
        q: [
          { type: "working" },
          { type: "working" },
          { type: "sentence", text: "Found it." },
          { type: "done", done: done("Found it.") },
        ],
      },
      log,
    );
    await new VoiceConversation(
      new ScriptedListener(["q"], log),
      speaker,
      ask,
      callbacks().cb,
    ).start();
    expect(speaker.spoken).toEqual([WORKING_PHRASE, "Found it."]);
  });

  it("stops after two turns in which nothing was heard", async () => {
    const log: string[] = [];
    const listener = new ScriptedListener([], log);
    const c = callbacks();
    const ask = vi.fn<Ask>();
    await new VoiceConversation(
      listener,
      new RecordingSpeaker(log),
      ask,
      c.cb,
    ).start();
    expect(listener.calls).toBe(2);
    expect(ask).not.toHaveBeenCalled();
    expect(c.errors).toEqual(["nothing_heard"]);
    expect(NOTHING_HEARD).toMatch(/Press Start/);
  });

  it("ends with the error when the assistant refuses, and drops the empty answer", async () => {
    const log: string[] = [];
    const ask = scriptedAsk(
      { q: [{ type: "error", code: "agent_unavailable", detail: "" }] },
      log,
    );
    const c = callbacks();
    await new VoiceConversation(
      new ScriptedListener(["q", "again"], log),
      new RecordingSpeaker(log),
      ask,
      c.cb,
    ).start();
    expect(c.errors).toEqual(["agent_unavailable"]);
    expect(c.turns().map((t) => t.role)).toEqual(["user"]);
    expect(log).not.toContain("ask:again");
  });

  it("Stop ends listening and speaking", async () => {
    const log: string[] = [];
    const speaker = new RecordingSpeaker(log, true);
    const listener = new ScriptedListener(["q"], log);
    const ask = scriptedAsk(
      {
        q: [
          { type: "sentence", text: "A long answer." },
          { type: "done", done: done("A long answer.") },
        ],
      },
      log,
    );
    const loop = new VoiceConversation(listener, speaker, ask, callbacks().cb);
    const running = loop.start();
    while (!speaker.spoken.length) await tick();
    loop.stop();
    await running;
    expect(listener.stopped).toBe(true);
    expect(speaker.cancelled).toBeGreaterThan(0);
    expect(loop.active).toBe(false);
  });

  it("an interruption stops speaking and listens again; the next question waits for the answer", async () => {
    const log: string[] = [];
    const speaker = new RecordingSpeaker(log, true);
    let finish!: () => void;
    const gate = new Promise<void>((resolve) => (finish = resolve));
    const ask = scriptedAsk(
      {
        first: [
          { type: "sentence", text: "Part one." },
          { type: "done", done: done("Part one. Part two.") },
        ],
        second: [
          { type: "sentence", text: "Ok." },
          { type: "done", done: done("Ok.") },
        ],
      },
      log,
      gate,
    );
    const listener = new ScriptedListener(["first", "second"], log);
    const c = callbacks();
    const loop = new VoiceConversation(listener, speaker, ask, c.cb);
    const running = loop.start();
    while (!speaker.spoken.length) await tick();
    loop.interrupt();
    while (listener.calls < 2) await tick();
    await tick();
    await tick();
    // Listening again, but "second" is not sent while "first" is still being answered.
    expect(log).not.toContain("ask:second");
    finish();
    while (!log.includes("ask:second")) await tick();
    // The interrupted answer was still finished and remembered in full.
    expect(c.turns()[1]).toMatchObject({
      role: "assistant",
      text: "Part one. Part two.",
      final: true,
    });
    loop.stop();
    await running;
  });
});

describe("the speech queue", () => {
  it("speaks in order and can be muted", async () => {
    const log: string[] = [];
    const speaker = new RecordingSpeaker(log);
    const started = vi.fn();
    const queue = new SpeechQueue(speaker, started);
    queue.add("One.");
    queue.add("Two.");
    queue.add("   ");
    await queue.idle();
    expect(speaker.spoken).toEqual(["One.", "Two."]);
    queue.mute();
    queue.add("Three.");
    await queue.idle();
    expect(speaker.spoken).toEqual(["One.", "Two."]);
    expect(started).toHaveBeenCalledTimes(2);
  });
});

describe("voice on the AI agents page", () => {
  it("shows minutes of server speech, not checks", async () => {
    const { voiceUsage } = await import("@/components/agent-views");
    expect(voiceUsage(0)).toMatch(/No server speech/);
    expect(voiceUsage(61)).toBe("About 2 minutes of server speech this month");
    expect(voiceUsage(30)).toBe("About 1 minute of server speech this month");
  });
});
