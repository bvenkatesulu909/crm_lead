// @vitest-environment node
// The voice route (ADR 0038, VR4): it does not exist unless the server key is set AND voice is on,
// it refuses audio that is empty, too big or of the wrong type before anything leaves this host,
// and it forwards a turn with the secret server key while the conversation token stays in a cookie.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const jar = new Map<string, string>();
const cookieSet = vi.fn();
vi.mock("next/headers", () => ({
  cookies: async () => ({
    get: (name: string) =>
      jar.has(name) ? { name, value: jar.get(name) } : undefined,
    set: cookieSet,
  }),
  headers: async () =>
    new Headers({ "x-nf-client-connection-ip": "203.0.113.9" }),
}));

const KEY = "k".repeat(40); // fictional, test only
const TOKEN = "T".repeat(54);

function env(overrides: Record<string, string> = {}) {
  vi.stubEnv("PUBLIC_CHAT_SERVER_KEY", KEY);
  vi.stubEnv("PUBLIC_CHAT_VOICE", "on");
  vi.stubEnv("APP_BASE_URL", "https://crm.example.test");
  vi.stubEnv("API_BASE_URL", "http://api.test/api/v1");
  vi.stubEnv("OIDC_ISSUER", "https://login.example.test/realms/crm");
  vi.stubEnv("OIDC_CLIENT_ID", "crm-web");
  vi.stubEnv("OIDC_CLIENT_SECRET", "s".repeat(24));
  vi.stubEnv("SESSION_SECRET", "A".repeat(43));
  for (const [name, value] of Object.entries(overrides))
    vi.stubEnv(name, value);
}

function turn(parts: Record<string, string | Blob | null>) {
  const form = new FormData();
  for (const [name, value] of Object.entries(parts)) {
    if (value === null) continue;
    if (typeof value === "string") form.set(name, value);
    else form.set(name, value, "turn.webm");
  }
  return new Request("https://crm.example.test/api/public-chat/voice", {
    method: "POST",
    body: form,
  });
}

const AUDIO = new Blob([new Uint8Array(500)], {
  type: "audio/webm;codecs=opus",
});
const API_OK = {
  token: TOKEN,
  heard: "Hello",
  reply: "Hi there",
  lead_saved: false,
  audio_base64: null,
  audio_type: null,
  seconds_left: 290,
  turns_left: 11,
  call_ended: false,
};

beforeEach(() => {
  jar.clear();
  cookieSet.mockClear();
});
afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

async function post(request: Request) {
  const { POST } = await import("./route");
  return POST(request);
}

describe("POST /api/public-chat/voice", () => {
  it("does not exist without the server key", async () => {
    env({ PUBLIC_CHAT_SERVER_KEY: "" });
    expect((await post(turn({ audio: AUDIO }))).status).toBe(404);
  });

  it("does not exist while voice is not switched on", async () => {
    env({ PUBLIC_CHAT_VOICE: "off" });
    const fetcher = vi.fn();
    vi.stubGlobal("fetch", fetcher);
    expect((await post(turn({ audio: AUDIO }))).status).toBe(404);
    expect(fetcher).not.toHaveBeenCalled();
  });

  it.each([
    ["no audio at all", { language: "en" }],
    ["an empty recording", { audio: new Blob([], { type: "audio/webm" }) }],
    [
      "a recording over 2 MB",
      {
        audio: new Blob([new Uint8Array(2 * 1024 * 1024 + 1)], {
          type: "audio/webm",
        }),
      },
    ],
    [
      "audio of a wrong type",
      { audio: new Blob([new Uint8Array(10)], { type: "text/html" }) },
    ],
    [
      "a script posing as audio",
      { audio: new Blob(["<script>"], { type: "application/javascript" }) },
    ],
  ])("refuses %s before anything leaves this host", async (_name, parts) => {
    env();
    const fetcher = vi.fn();
    vi.stubGlobal("fetch", fetcher);
    const response = await post(turn(parts as Record<string, string | Blob>));
    expect(response.status).toBe(422);
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("forwards a turn with the server key and keeps the token in a cookie", async () => {
    env();
    jar.set("crm_chat", TOKEN);
    const fetcher = vi
      .fn()
      .mockResolvedValue(Response.json(API_OK, { status: 200 }));
    vi.stubGlobal("fetch", fetcher);
    const response = await post(
      turn({ audio: AUDIO, language: "hi", consent_version: "1", website: "" }),
    );
    expect(response.status).toBe(200);
    const [url, init] = fetcher.mock.calls[0];
    expect(url).toBe("http://api.test/api/v1/public/voice/turn");
    expect(init.headers).toMatchObject({
      "X-Public-Chat-Key": KEY,
      "X-Visitor-Ip": "203.0.113.9",
    });
    const form = init.body as FormData;
    expect(form.get("language")).toBe("hi");
    expect(form.get("consent_version")).toBe("1");
    expect(form.get("token")).toBe(TOKEN);
    // The browser gets the answer, never the token or the key.
    const body = await response.json();
    expect(body.reply).toBe("Hi there");
    expect(JSON.stringify(body)).not.toContain(TOKEN);
    expect(JSON.stringify(body)).not.toContain(KEY);
    expect(response.headers.get("Cache-Control")).toBe("no-store");
    expect(cookieSet).toHaveBeenCalledWith(
      "crm_chat",
      TOKEN,
      expect.objectContaining({ httpOnly: true, path: "/api/public-chat" }),
    );
  });

  it("sends no consent when the page sent something that is not a version", async () => {
    env();
    const fetcher = vi.fn().mockResolvedValue(Response.json(API_OK));
    vi.stubGlobal("fetch", fetcher);
    await post(turn({ audio: AUDIO, consent_version: "yes please" }));
    expect(
      (fetcher.mock.calls[0][1].body as FormData).has("consent_version"),
    ).toBe(false);
  });

  it("passes the API's refusal on and leaves the cookie alone", async () => {
    env();
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          Response.json(
            { code: "voice_consent_required", detail: "Press Start." },
            { status: 422 },
          ),
        ),
    );
    const response = await post(turn({ audio: AUDIO }));
    expect(response.status).toBe(422);
    expect((await response.json()).code).toBe("voice_consent_required");
    expect(cookieSet).not.toHaveBeenCalled();
  });
});
