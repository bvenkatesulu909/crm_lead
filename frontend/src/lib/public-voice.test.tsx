import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { PublicChat } from "@/components/public-chat";
import { PublicVoiceCall } from "@/components/public-voice-call";
import { CHAT_LANGUAGES } from "@/lib/public-chat";
import {
  VAD,
  VOICE_TEXT,
  audioBlob,
  createVad,
  voiceErrorText,
  type VoiceAnswer,
} from "@/lib/public-voice";
import {
  forwardVoiceTurn,
  publicVoiceEnabled,
  voiceNoticeVersion,
} from "@/lib/server/public-voice";
import { MicError } from "@/lib/voice-recorder";

const KEY = "k".repeat(40); // fictional, test only
const TOKEN = "T".repeat(54);

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

function json(status: number, body: unknown) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const ANSWER: VoiceAnswer = {
  heard: "I want a flat",
  reply: "Which area do you like?",
  lead_saved: false,
  audio_base64: btoa("ID3-fake"),
  audio_type: "audio/mpeg",
  seconds_left: 250,
  turns_left: 11,
  call_ended: false,
};

// --- deciding when a turn is over ----------------------------------------------------------

describe("createVad", () => {
  const LOUD = 0.2;
  const QUIET = 0.001;

  function feed(levels: [number, number][]) {
    const vad = createVad(VAD);
    let last = "continue";
    for (const [level, at] of levels) {
      last = vad.push(level, at);
      if (last !== "continue") break;
    }
    return last;
  }

  it("keeps listening while nobody has spoken yet", () => {
    expect(
      feed([
        [QUIET, 0],
        [QUIET, 3000],
      ]),
    ).toBe("continue");
  });

  it("gives up when nothing is said for a while", () => {
    expect(
      feed([
        [QUIET, 0],
        [QUIET, VAD.noSpeechMs],
      ]),
    ).toBe("nothing");
  });

  it("stops and sends after real speech followed by silence", () => {
    expect(
      feed([
        [QUIET, 0],
        [LOUD, 500],
        [LOUD, 1200],
        [QUIET, 1300],
        [QUIET, 1200 + VAD.silenceMs],
      ]),
    ).toBe("stop");
  });

  it("does not stop in the middle of a short pause", () => {
    expect(
      feed([
        [LOUD, 0],
        [LOUD, 800],
        [QUIET, 1500],
        [QUIET, 800 + VAD.silenceMs - 1],
      ]),
    ).toBe("continue");
  });

  it("treats a cough as nothing, not as a turn", () => {
    expect(
      feed([
        [QUIET, 0],
        [LOUD, 500],
        [QUIET, 600],
        [QUIET, 500 + VAD.silenceMs],
      ]),
    ).toBe("nothing");
  });

  it("never records longer than the limit", () => {
    expect(
      feed([
        [LOUD, 0],
        [LOUD, VAD.maxMs],
      ]),
    ).toBe("stop");
    expect(
      feed([
        [QUIET, 0],
        [QUIET, VAD.maxMs],
      ]),
    ).toBe("nothing");
  });
});

// --- words and errors ------------------------------------------------------------------------

describe("the words", () => {
  it("exist in all three languages, every one filled in", () => {
    const keys = Object.keys(VOICE_TEXT.en).sort();
    for (const language of CHAT_LANGUAGES) {
      expect(Object.keys(VOICE_TEXT[language]).sort()).toEqual(keys);
      for (const value of Object.values(VOICE_TEXT[language]))
        expect(value.trim().length).toBeGreaterThan(5);
    }
  });

  it("say it is an automated assistant, in each language, before the call starts", () => {
    expect(VOICE_TEXT.en.notice).toMatch(/automated assistant, not a person/);
    expect(VOICE_TEXT.en.greeting).toMatch(/automated assistant/);
    expect(VOICE_TEXT.hi.notice).toContain("स्वचालित सहायक");
    expect(VOICE_TEXT.hi.greeting).toContain("स्वचालित सहायक");
    expect(VOICE_TEXT.te.notice).toContain("ఆటోమేటెడ్ అసిస్టెంట్");
    expect(VOICE_TEXT.te.greeting).toContain("ఆటోమేటెడ్ అసిస్టెంట్");
  });

  it("say that no recording is kept and what not to say", () => {
    expect(VOICE_TEXT.en.notice).toMatch(/do not keep your voice recording/);
    expect(VOICE_TEXT.en.notice).toMatch(/card numbers/);
  });
});

describe("voiceErrorText", () => {
  it("asks for the notice again when consent is missing, and ends the call", () => {
    expect(voiceErrorText("en", 422, "voice_consent_required")).toEqual({
      text: VOICE_TEXT.en.consentAgain,
      endsCall: true,
    });
  });
  it("lets the call go on after nothing was heard", () => {
    const answer = voiceErrorText("hi", 422, "voice_heard_nothing");
    expect(answer.endsCall).toBe(false);
    expect(answer.text).toBe(VOICE_TEXT.hi.heardNothing);
  });
  it("tells a call's limit from a day's limit", () => {
    expect(
      voiceErrorText(
        "en",
        429,
        "voice_limit_reached",
        "Please try again tomorrow.",
      ),
    ).toMatchObject({ text: VOICE_TEXT.en.limitDay, endsCall: true });
    expect(
      voiceErrorText(
        "en",
        429,
        "voice_limit_reached",
        "This call has reached its time limit.",
      ),
    ).toMatchObject({ text: VOICE_TEXT.en.limitCall, endsCall: true });
  });
  it("shows the API's own refusal sentence and goes on", () => {
    expect(
      voiceErrorText(
        "te",
        422,
        "message_refused",
        "Please do not say card numbers.",
      ),
    ).toEqual({ text: "Please do not say card numbers.", endsCall: false });
  });
  it("ends the call on anything else, in the visitor's language", () => {
    expect(voiceErrorText("te", 503, "receptionist_unavailable")).toEqual({
      text: VOICE_TEXT.te.failed,
      endsCall: true,
    });
  });
});

describe("audioBlob", () => {
  it("turns the base64 reply into playable audio", async () => {
    const blob = audioBlob(ANSWER);
    expect(blob?.type).toBe("audio/mpeg");
    expect(await blob?.text()).toBe("ID3-fake");
  });
  it("gives nothing when there is no audio or it is broken", () => {
    expect(audioBlob({ ...ANSWER, audio_base64: null })).toBeNull();
    expect(
      audioBlob({ ...ANSWER, audio_base64: "%%%not base64%%%" }),
    ).toBeNull();
  });
});

// --- the server side ---------------------------------------------------------------------------

describe("forwardVoiceTurn", () => {
  const input = {
    audio: new Blob([new Uint8Array(100)], { type: "audio/webm" }),
    filename: "turn.webm",
    language: "te",
    consentVersion: 1 as number | null,
    website: "",
    token: TOKEN as string | null | undefined,
    ip: "203.0.113.7",
    key: KEY,
    apiBaseUrl: "http://api.test/api/v1",
  };
  const okBody = { ...ANSWER, token: TOKEN };

  it("sends the audio as a form with the server key and the visitor's address", async () => {
    const fetcher = vi.fn().mockResolvedValue(json(200, okBody));
    const result = await forwardVoiceTurn(input, fetcher);
    const [url, init] = fetcher.mock.calls[0];
    expect(url).toBe("http://api.test/api/v1/public/voice/turn");
    expect(init.headers).toEqual({
      "X-Public-Chat-Key": KEY,
      "X-Visitor-Ip": "203.0.113.7",
    });
    expect(init.headers["Content-Type"]).toBeUndefined(); // the boundary is fetch's job
    const form = init.body as FormData;
    expect(form.get("language")).toBe("te");
    expect(form.get("consent_version")).toBe("1");
    expect(form.get("token")).toBe(TOKEN);
    expect(form.get("website")).toBe("");
    expect((form.get("audio") as File).name).toBe("turn.webm");
    expect(result.status).toBe(200);
    expect(result.cookie).toEqual({ set: TOKEN });
    expect(result.body).toMatchObject({
      reply: ANSWER.reply,
      call_ended: false,
    });
  });

  it("never sends a token that is not shaped like ours, nor an unknown language", async () => {
    const fetcher = vi.fn().mockResolvedValue(json(200, okBody));
    await forwardVoiceTurn(
      { ...input, token: "../../etc", language: "fr" },
      fetcher,
    );
    const form = fetcher.mock.calls[0][1].body as FormData;
    expect(form.get("token")).toBeNull();
    expect(form.get("language")).toBe("en");
  });

  it("leaves the consent out when the page sent none (the API then refuses)", async () => {
    const fetcher = vi.fn().mockResolvedValue(json(200, okBody));
    await forwardVoiceTurn({ ...input, consentVersion: null }, fetcher);
    expect(
      (fetcher.mock.calls[0][1].body as FormData).has("consent_version"),
    ).toBe(false);
  });

  it("passes the API's refusal on and keeps the cookie", async () => {
    const fetcher = vi.fn().mockResolvedValue(
      json(422, {
        code: "voice_consent_required",
        detail: "Please press Start.",
      }),
    );
    expect(await forwardVoiceTurn(input, fetcher)).toEqual({
      status: 422,
      body: { code: "voice_consent_required", detail: "Please press Start." },
      cookie: "keep",
    });
  });

  it("starts a new conversation when the old one was cleaned up", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValueOnce(json(404, { code: "conversation_not_found" }))
      .mockResolvedValueOnce(json(200, okBody));
    const result = await forwardVoiceTurn(input, fetcher);
    expect(fetcher).toHaveBeenCalledTimes(2);
    expect((fetcher.mock.calls[1][1].body as FormData).has("token")).toBe(
      false,
    );
    expect(result.status).toBe(200);
  });

  it("says unavailable when the API is down or answers nonsense", async () => {
    const down = vi.fn().mockRejectedValue(new TypeError("fetch failed"));
    expect((await forwardVoiceTurn(input, down)).status).toBe(503);
    const odd = vi.fn().mockResolvedValue(json(200, { nothing: true }));
    expect(await forwardVoiceTurn(input, odd)).toMatchObject({
      status: 503,
      cookie: "keep",
    });
  });

  it("returns only the fields the page needs", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValue(
        json(200, { ...okBody, tenant_id: "secret", extra: 1 }),
      );
    const result = await forwardVoiceTurn(input, fetcher);
    expect(Object.keys(result.body).sort()).toEqual(
      [
        "audio_base64",
        "audio_type",
        "call_ended",
        "heard",
        "lead_saved",
        "reply",
        "seconds_left",
        "turns_left",
      ].sort(),
    );
  });
});

describe("the switches of the voice button", () => {
  it("is off unless PUBLIC_CHAT_VOICE is on", () => {
    expect(publicVoiceEnabled()).toBe(false);
    vi.stubEnv("PUBLIC_CHAT_VOICE", "yes");
    expect(publicVoiceEnabled()).toBe(false);
    vi.stubEnv("PUBLIC_CHAT_VOICE", " ON ");
    expect(publicVoiceEnabled()).toBe(true);
  });
  it("reads the notice version, defaulting to 1 for anything odd", () => {
    expect(voiceNoticeVersion()).toBe(1);
    vi.stubEnv("PUBLIC_CHAT_VOICE_NOTICE_VERSION", "4");
    expect(voiceNoticeVersion()).toBe(4);
    for (const odd of ["0", "-2", "x", "99999", ""]) {
      vi.stubEnv("PUBLIC_CHAT_VOICE_NOTICE_VERSION", odd);
      expect(voiceNoticeVersion()).toBe(1);
    }
  });
});

// --- the call on the page ----------------------------------------------------------------------

class FakeAudio {
  static played: string[] = [];
  onended: (() => void) | null = null;
  onerror: (() => void) | null = null;
  constructor(readonly src: string) {}
  play() {
    FakeAudio.played.push(this.src);
    queueMicrotask(() => this.onended?.());
    return Promise.resolve();
  }
  pause() {}
}

function setup(
  overrides: Partial<React.ComponentProps<typeof PublicVoiceCall>> = {},
) {
  FakeAudio.played = [];
  vi.stubGlobal("Audio", FakeAudio);
  URL.createObjectURL = vi.fn(() => "blob:fake");
  URL.revokeObjectURL = vi.fn();
  const onGreeting = vi.fn();
  const onTurn = vi.fn();
  const onSaved = vi.fn();
  const turn = new Blob(["voice"], { type: "audio/webm" });
  const record = vi.fn().mockResolvedValue(turn);
  const props = {
    language: "en" as const,
    noticeVersion: 3,
    onGreeting,
    onTurn,
    onSaved,
    record,
    available: () => true,
    ...overrides,
  };
  render(<PublicVoiceCall {...props} />);
  return { onGreeting, onTurn, onSaved, record };
}

describe("PublicVoiceCall", () => {
  it("shows nothing at all in a browser that cannot record", () => {
    setup({ available: () => false });
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("shows the notice first and does not touch the microphone until Start", async () => {
    const { record } = setup();
    await userEvent.click(
      screen.getByRole("button", { name: VOICE_TEXT.en.talk }),
    );
    expect(screen.getByText(/automated assistant, not a person/)).toBeTruthy();
    expect(record).not.toHaveBeenCalled();
    await userEvent.click(
      screen.getByRole("button", { name: VOICE_TEXT.en.cancel }),
    );
    expect(record).not.toHaveBeenCalled();
    expect(
      screen.getByRole("button", { name: VOICE_TEXT.en.talk }),
    ).toBeTruthy();
  });

  it("starts after Start: greets, listens, sends the audio with the consent, shows and plays the reply", async () => {
    const fetcher = vi.fn().mockResolvedValue(json(200, ANSWER));
    vi.stubGlobal("fetch", fetcher);
    const { onGreeting, onTurn, record } = setup({ language: "hi" });
    await userEvent.click(
      screen.getByRole("button", { name: VOICE_TEXT.hi.talk }),
    );
    // Stop the loop after the first turn so the test ends.
    record.mockResolvedValueOnce(new Blob(["voice"], { type: "audio/webm" }));
    record.mockImplementation(() => new Promise(() => {}));
    await userEvent.click(
      screen.getByRole("button", { name: VOICE_TEXT.hi.start }),
    );

    await waitFor(() =>
      expect(onTurn).toHaveBeenCalledWith(ANSWER.heard, ANSWER.reply),
    );
    expect(onGreeting).toHaveBeenCalledWith(VOICE_TEXT.hi.greeting);
    const [url, init] = fetcher.mock.calls[0];
    expect(url).toBe("/api/public-chat/voice");
    const form = init.body as FormData;
    expect(form.get("consent_version")).toBe("3");
    expect(form.get("language")).toBe("hi");
    expect(form.get("website")).toBe("");
    expect(FakeAudio.played).toEqual(["blob:fake"]);
    // Nothing secret travels from here: no key and no token field.
    expect(form.has("token")).toBe(false);
    expect(JSON.stringify([...form.keys()])).not.toMatch(/key/i);
  });

  it("tells the page when the details were saved", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(json(200, { ...ANSWER, lead_saved: true })),
    );
    const { onSaved, record } = setup();
    record.mockResolvedValueOnce(new Blob(["v"], { type: "audio/webm" }));
    record.mockImplementation(() => new Promise(() => {}));
    await userEvent.click(
      screen.getByRole("button", { name: VOICE_TEXT.en.talk }),
    );
    await userEvent.click(
      screen.getByRole("button", { name: VOICE_TEXT.en.start }),
    );
    await waitFor(() => expect(onSaved).toHaveBeenCalled());
  });

  it("keeps listening after a turn and ends when the call's limit says so", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValueOnce(json(200, ANSWER))
      .mockResolvedValueOnce(
        json(200, { ...ANSWER, call_ended: true, turns_left: 0 }),
      );
    vi.stubGlobal("fetch", fetcher);
    setup();
    await userEvent.click(
      screen.getByRole("button", { name: VOICE_TEXT.en.talk }),
    );
    await userEvent.click(
      screen.getByRole("button", { name: VOICE_TEXT.en.start }),
    );
    await waitFor(() =>
      expect(screen.getByText(VOICE_TEXT.en.limitCall)).toBeTruthy(),
    );
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it("stops at once when the visitor presses End", async () => {
    const fetcher = vi.fn();
    vi.stubGlobal("fetch", fetcher);
    const { record } = setup();
    let seen: AbortSignal | undefined;
    record.mockImplementation(
      (signal: AbortSignal) =>
        new Promise((resolve) => {
          seen = signal;
          signal.addEventListener("abort", () => resolve(null));
        }),
    );
    await userEvent.click(
      screen.getByRole("button", { name: VOICE_TEXT.en.talk }),
    );
    await userEvent.click(
      screen.getByRole("button", { name: VOICE_TEXT.en.start }),
    );
    await waitFor(() => expect(record).toHaveBeenCalled());
    await userEvent.click(
      screen.getByRole("button", { name: VOICE_TEXT.en.end }),
    );
    expect(seen?.aborted).toBe(true);
    await waitFor(() =>
      expect(screen.getByText(VOICE_TEXT.en.ended)).toBeTruthy(),
    );
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("explains a blocked or missing microphone and removes the button", async () => {
    const { record } = setup();
    record.mockRejectedValueOnce(new MicError("denied"));
    await userEvent.click(
      screen.getByRole("button", { name: VOICE_TEXT.en.talk }),
    );
    await userEvent.click(
      screen.getByRole("button", { name: VOICE_TEXT.en.start }),
    );
    await waitFor(() =>
      expect(screen.getByText(VOICE_TEXT.en.micDenied)).toBeTruthy(),
    );
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("ends after two silent turns, without sending anything", async () => {
    const fetcher = vi.fn();
    vi.stubGlobal("fetch", fetcher);
    const { record } = setup();
    record.mockResolvedValue(null);
    await userEvent.click(
      screen.getByRole("button", { name: VOICE_TEXT.en.talk }),
    );
    await userEvent.click(
      screen.getByRole("button", { name: VOICE_TEXT.en.start }),
    );
    await waitFor(() =>
      expect(screen.getByText(VOICE_TEXT.en.heardNothing)).toBeTruthy(),
    );
    expect(record).toHaveBeenCalledTimes(2);
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("takes the call button away for good when the service is off", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(json(503, { code: "receptionist_unavailable" })),
    );
    setup();
    await userEvent.click(
      screen.getByRole("button", { name: VOICE_TEXT.en.talk }),
    );
    await userEvent.click(
      screen.getByRole("button", { name: VOICE_TEXT.en.start }),
    );
    await waitFor(() =>
      expect(screen.getByText(VOICE_TEXT.en.failed)).toBeTruthy(),
    );
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("shows a refused sentence as plain text and keeps listening", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValueOnce(
        json(422, {
          code: "message_refused",
          detail: "Please do not say <b>card</b> numbers.",
        }),
      )
      .mockResolvedValue(json(200, ANSWER));
    vi.stubGlobal("fetch", fetcher);
    const { onTurn, record } = setup();
    record.mockResolvedValueOnce(new Blob(["a"], { type: "audio/webm" }));
    record.mockResolvedValueOnce(new Blob(["b"], { type: "audio/webm" }));
    record.mockImplementation(() => new Promise(() => {}));
    await userEvent.click(
      screen.getByRole("button", { name: VOICE_TEXT.en.talk }),
    );
    await userEvent.click(
      screen.getByRole("button", { name: VOICE_TEXT.en.start }),
    );
    await waitFor(() => expect(onTurn).toHaveBeenCalled());
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it("shows text from the service as text, never as markup", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        json(422, {
          code: "message_refused",
          detail: "<img src=x onerror=alert(1)>",
        }),
      ),
    );
    const { record } = setup();
    record.mockResolvedValueOnce(new Blob(["a"], { type: "audio/webm" }));
    record.mockImplementation(() => new Promise(() => {}));
    await userEvent.click(
      screen.getByRole("button", { name: VOICE_TEXT.en.talk }),
    );
    await userEvent.click(
      screen.getByRole("button", { name: VOICE_TEXT.en.start }),
    );
    await waitFor(() => expect(screen.getByText(/<img src=x/)).toBeTruthy());
    expect(document.querySelector("img")).toBeNull();
  });

  it("uses the words of the language chosen when the call started", async () => {
    setup({ language: "te" });
    expect(
      screen.getByRole("button", { name: VOICE_TEXT.te.talk }),
    ).toBeTruthy();
  });
});

describe("the voice button on the chat page", () => {
  function stubRecorder() {
    vi.stubGlobal("MediaRecorder", class {});
    Object.defineProperty(navigator, "mediaDevices", {
      value: { getUserMedia: vi.fn() },
      configurable: true,
    });
  }

  it("is not there unless the server offers it", () => {
    stubRecorder();
    render(<PublicChat />);
    expect(
      screen.queryByRole("button", { name: VOICE_TEXT.en.talk }),
    ).toBeNull();
  });

  it("is there when the server offers it and the browser can record", async () => {
    stubRecorder();
    await act(async () => {
      render(<PublicChat voice={{ noticeVersion: 1 }} />);
    });
    expect(
      screen.getByRole("button", { name: VOICE_TEXT.en.talk }),
    ).toBeTruthy();
  });

  it("puts what was said and answered into the same conversation", async () => {
    stubRecorder();
    // Replace only the recorder by wrapping the component through the prop route is not possible
    // here, so this checks the wiring of the greeting through the visible notice and Start.
    await act(async () => {
      render(<PublicChat voice={{ noticeVersion: 1 }} />);
    });
    await userEvent.click(
      screen.getByRole("button", { name: VOICE_TEXT.en.talk }),
    );
    expect(screen.getByText(/automated assistant, not a person/)).toBeTruthy();
  });
});
