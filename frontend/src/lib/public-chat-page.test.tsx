import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { PublicChat } from "@/components/public-chat";
import {
  CHAT_LANGUAGES,
  CHAT_TEXT,
  SPEECH_LANG,
  chatErrorText,
  checkVisitorMessage,
  isChatLanguage,
  pickLanguage,
} from "@/lib/public-chat";
import {
  CHAT_COOKIE,
  chatCookieOptions,
  forwardChat,
  publicChatKey,
  visitorIp,
} from "@/lib/server/public-chat";

const KEY = "k".repeat(40); // fictional, test only
const TOKEN = "T".repeat(54);

function reply(status: number, body: unknown) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

// --- rules shared by the page and the server ------------------------------------------------

describe("checkVisitorMessage", () => {
  it("accepts a normal message and refuses empty or very long ones", () => {
    expect(checkVisitorMessage("Hi, I want a 3BHK")).toBeNull();
    expect(checkVisitorMessage("   ")).toMatch(/type a message/i);
    expect(checkVisitorMessage("x".repeat(2001))).toMatch(/2,000/);
  });
});

describe("chatErrorText", () => {
  it("turns the API's answers into friendly words", () => {
    expect(chatErrorText(429, "public_chat_rate_limited")).toMatch(/wait/i);
    expect(chatErrorText(429, "public_chat_busy")).toMatch(/busy/i);
    expect(chatErrorText(503)).toMatch(/not available/i);
    expect(chatErrorText(404)).toMatch(/not available/i);
    expect(
      chatErrorText(422, "message_refused", "We can't take card numbers here."),
    ).toBe("We can't take card numbers here.");
    expect(chatErrorText(500)).toMatch(/went wrong/i);
  });
});

// --- the Next.js server side ------------------------------------------------------------------

describe("visitorIp", () => {
  it("takes the first address the hosting proxy saw", () => {
    const headers = new Headers({ "x-forwarded-for": "203.0.113.7, 10.0.0.1" });
    expect(visitorIp(headers)).toBe("203.0.113.7");
    expect(visitorIp(new Headers({ "x-real-ip": "198.51.100.4" }))).toBe(
      "198.51.100.4",
    );
    expect(visitorIp(new Headers())).toBe("");
    // Anything that isn't an address is dropped (the API then limits it as "unknown").
    expect(visitorIp(new Headers({ "x-forwarded-for": "<script>" }))).toBe("");
  });

  it("prefers the address Netlify itself saw over one the visitor could fake", () => {
    const headers = new Headers({
      "x-nf-client-connection-ip": "203.0.113.9",
      "x-forwarded-for": "198.51.100.1",
    });
    expect(visitorIp(headers)).toBe("203.0.113.9");
  });
});

describe("chatCookieOptions", () => {
  it("keeps the conversation token away from page JavaScript", () => {
    const options = chatCookieOptions(true);
    expect(CHAT_COOKIE).toBe("crm_chat");
    expect(options).toMatchObject({
      httpOnly: true,
      secure: true,
      sameSite: "lax",
      path: "/api/public-chat",
    });
    expect(chatCookieOptions(false).secure).toBe(false);
  });
});

describe("publicChatKey", () => {
  afterEach(() => vi.unstubAllEnvs());

  it("is off without a long enough key", () => {
    vi.stubEnv("PUBLIC_CHAT_SERVER_KEY", "");
    expect(publicChatKey()).toBeNull();
    vi.stubEnv("PUBLIC_CHAT_SERVER_KEY", "short");
    expect(publicChatKey()).toBeNull();
    vi.stubEnv("PUBLIC_CHAT_SERVER_KEY", KEY);
    expect(publicChatKey()).toBe(KEY);
  });
});

describe("forwardChat", () => {
  const base = {
    message: "Hello",
    website: "",
    ip: "203.0.113.7",
    key: KEY,
    apiBaseUrl: "http://api.test/api/v1",
  };

  it("adds the server key and the visitor address, and keeps the token on the server", async () => {
    const fetcher = vi.fn().mockResolvedValue(
      reply(200, {
        token: TOKEN,
        reply: "Hi! Your phone number?",
        lead_saved: false,
      }),
    );
    const result = await forwardChat({ ...base, token: null }, fetcher);

    const [url, init] = fetcher.mock.calls[0];
    expect(url).toBe("http://api.test/api/v1/public/chat");
    expect(init.headers).toMatchObject({
      "X-Public-Chat-Key": KEY,
      "X-Visitor-Ip": "203.0.113.7",
    });
    expect(JSON.parse(init.body)).toEqual({
      message: "Hello",
      website: "",
      language: "en",
    });
    expect(result.status).toBe(200);
    expect(result.body).toEqual({
      reply: "Hi! Your phone number?",
      lead_saved: false,
    });
    expect(JSON.stringify(result.body)).not.toContain(TOKEN); // the browser never sees it
    expect(result.cookie).toEqual({ set: TOKEN });
  });

  it("sends the saved token with the next message", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValue(
        reply(200, { token: TOKEN, reply: "Thanks", lead_saved: true }),
      );
    await forwardChat({ ...base, token: TOKEN }, fetcher);
    expect(JSON.parse(fetcher.mock.calls[0][1].body).token).toBe(TOKEN);
  });

  it("ignores a cookie that isn't a token's shape", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValue(
        reply(200, { token: TOKEN, reply: "Hi", lead_saved: false }),
      );
    await forwardChat({ ...base, token: "../../etc" }, fetcher);
    expect(JSON.parse(fetcher.mock.calls[0][1].body)).not.toHaveProperty(
      "token",
    );
  });

  it("starts a new conversation once when the old one was deleted", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValueOnce(
        reply(404, { code: "conversation_not_found", detail: "gone" }),
      )
      .mockResolvedValueOnce(
        reply(200, { token: TOKEN, reply: "Hello again", lead_saved: false }),
      );
    const result = await forwardChat(
      { ...base, token: "A".repeat(43) },
      fetcher,
    );
    expect(fetcher).toHaveBeenCalledTimes(2);
    expect(JSON.parse(fetcher.mock.calls[1][1].body)).not.toHaveProperty(
      "token",
    );
    expect(result.status).toBe(200);
  });

  it("passes refusals on with their code, and the API being down as 503", async () => {
    const refused = vi
      .fn()
      .mockResolvedValue(
        reply(429, { code: "public_chat_rate_limited", detail: "Wait" }),
      );
    expect(await forwardChat({ ...base, token: null }, refused)).toMatchObject({
      status: 429,
      body: { code: "public_chat_rate_limited" },
      cookie: "keep",
    });
    const down = vi.fn().mockRejectedValue(new TypeError("fetch failed"));
    expect((await forwardChat({ ...base, token: null }, down)).status).toBe(
      503,
    );
  });
});

// --- the page -------------------------------------------------------------------------------

describe("PublicChat", () => {
  it("shows the privacy notice before the first message", () => {
    render(<PublicChat privacyUrl="https://example.test/privacy" />);
    expect(
      screen.getByText(/stored to answer your enquiry/i),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /privacy/i })).toHaveAttribute(
      "href",
      "https://example.test/privacy",
    );
  });

  it("sends a message and shows the answer as plain text", async () => {
    const fetcher = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      reply(200, {
        reply: "<img src=x> May I have your phone number?",
        lead_saved: false,
      }),
    );
    const { container } = render(<PublicChat />);
    await userEvent.type(
      screen.getByLabelText("Your message"),
      "Hi, I want a flat",
    );
    await userEvent.click(screen.getByRole("button", { name: "Send" }));

    expect(
      await screen.findByText(/May I have your phone number/),
    ).toBeInTheDocument();
    expect(screen.getByText("Hi, I want a flat")).toBeInTheDocument();
    expect(container.querySelector("img")).toBeNull(); // shown as text, never as HTML
    const [url, init] = fetcher.mock.calls[0];
    expect(url).toBe("/api/public-chat");
    expect(JSON.parse(String(init?.body))).toEqual({
      message: "Hi, I want a flat",
      website: "",
      language: "en",
    });
    expect(screen.getByLabelText("Your message")).toHaveValue("");
  });

  it("says when the details were passed on", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      reply(200, {
        reply: "Thank you! An advisor will call you.",
        lead_saved: true,
      }),
    );
    render(<PublicChat />);
    await userEvent.type(
      screen.getByLabelText("Your message"),
      "Suresh, 98480 12345",
    );
    await userEvent.click(screen.getByRole("button", { name: "Send" }));
    expect(await screen.findByRole("status")).toHaveTextContent(
      /passed on to our team/i,
    );
  });

  it("keeps the text and explains when the message was refused", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      reply(429, { code: "public_chat_rate_limited", detail: "Too many" }),
    );
    render(<PublicChat />);
    await userEvent.type(screen.getByLabelText("Your message"), "Hello");
    await userEvent.click(screen.getByRole("button", { name: "Send" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/wait/i);
    expect(screen.getByLabelText("Your message")).toHaveValue("Hello");
  });

  it("refuses an empty message without calling the server", async () => {
    const fetcher = vi.spyOn(globalThis, "fetch");
    render(<PublicChat />);
    await userEvent.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent(/type a message/i),
    );
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("has a hidden honeypot field that people don't see", () => {
    const { container } = render(<PublicChat />);
    const trap = container.querySelector<HTMLInputElement>(
      'input[name="website"]',
    );
    expect(trap).not.toBeNull();
    expect(trap?.tabIndex).toBe(-1);
    expect(trap?.closest("[aria-hidden='true']")).not.toBeNull();
  });
});

// --- languages and speech (ADR 0027, step VL2) ---------------------------------------------

describe("chat languages", () => {
  it("knows exactly three languages and refuses anything else", () => {
    expect([...CHAT_LANGUAGES]).toEqual(["en", "hi", "te"]);
    for (const ok of CHAT_LANGUAGES) expect(isChatLanguage(ok)).toBe(true);
    for (const bad of ["fr", "HI", "", "hi\nx", 5, null, undefined])
      expect(isChatLanguage(bad)).toBe(false);
  });

  it("picks the browser's language when it is one of the three, else English", () => {
    expect(pickLanguage(["hi-IN", "en-US"])).toBe("hi");
    expect(pickLanguage(["te"])).toBe("te");
    expect(pickLanguage(["fr-FR", "te-IN"])).toBe("te");
    expect(pickLanguage(["fr-FR", "de"])).toBe("en");
    expect(pickLanguage([])).toBe("en");
    expect(pickLanguage(undefined)).toBe("en");
  });

  it("has every word for every language, and speech tags for India", () => {
    const keys = Object.keys(CHAT_TEXT.en).sort();
    for (const code of CHAT_LANGUAGES) {
      expect(Object.keys(CHAT_TEXT[code]).sort()).toEqual(keys);
      for (const value of Object.values(CHAT_TEXT[code]))
        expect(value.length).toBeGreaterThan(2);
    }
    expect(SPEECH_LANG).toEqual({ en: "en-IN", hi: "hi-IN", te: "te-IN" });
  });
});

describe("forwardChat with a language", () => {
  const base = {
    message: "Hello",
    website: "",
    ip: "203.0.113.7",
    key: KEY,
    apiBaseUrl: "http://api.test/api/v1",
    token: null,
  };

  it("passes the chosen language on to the API", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValue(
        reply(200, { token: TOKEN, reply: "ok", lead_saved: false }),
      );
    await forwardChat({ ...base, language: "te" }, fetcher);
    expect(JSON.parse(fetcher.mock.calls[0][1].body).language).toBe("te");
  });
});

describe("PublicChat in Hindi and Telugu", () => {
  function fakeRecognition() {
    const instances: {
      lang: string;
      interimResults: boolean;
      continuous: boolean;
      start: ReturnType<typeof vi.fn>;
      stop: ReturnType<typeof vi.fn>;
      onresult: ((e: unknown) => void) | null;
      onend: (() => void) | null;
      onerror: (() => void) | null;
    }[] = [];
    class Recognition {
      lang = "";
      interimResults = false;
      continuous = false;
      start = vi.fn();
      stop = vi.fn();
      onresult: ((e: unknown) => void) | null = null;
      onend: (() => void) | null = null;
      onerror: (() => void) | null = null;
      constructor() {
        instances.push(this);
      }
    }
    vi.stubGlobal("webkitSpeechRecognition", Recognition);
    return instances;
  }

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("starts in English and shows the three languages written in themselves", () => {
    render(<PublicChat />);
    expect(
      screen.getByText(/Hello! I can help you find a home/),
    ).toBeInTheDocument();
    const group = screen.getByRole("group", { name: "Language" });
    expect(group).toHaveTextContent("English");
    expect(group).toHaveTextContent("हिन्दी");
    expect(group).toHaveTextContent("తెలుగు");
  });

  it("switches the greeting, buttons and placeholder to Hindi", async () => {
    render(<PublicChat />);
    await userEvent.click(screen.getByRole("button", { name: "हिन्दी" }));
    expect(screen.getByText(/नमस्ते!/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "भेजें" })).toBeInTheDocument();
    expect(
      screen.getByPlaceholderText("अपना संदेश लिखें…"),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "हिन्दी" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("sends the chosen language with the message", async () => {
    const fetcher = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(reply(200, { reply: "ठीक है", lead_saved: false }));
    render(<PublicChat />);
    await userEvent.click(screen.getByRole("button", { name: "తెలుగు" }));
    await userEvent.type(
      screen.getByLabelText("మీ సందేశం"),
      "నాకు ఫ్లాట్ కావాలి",
    );
    await userEvent.click(screen.getByRole("button", { name: "పంపండి" }));
    await screen.findByText("ठीक है");
    expect(JSON.parse(String(fetcher.mock.calls[0][1]?.body)).language).toBe(
      "te",
    );
  });

  it("shows no microphone when the browser has no speech recognition", () => {
    render(<PublicChat />);
    expect(screen.queryByRole("button", { name: "Speak" })).toBeNull();
  });

  it("listens in the chosen language and puts what it heard in the message box", async () => {
    const instances = fakeRecognition();
    render(<PublicChat />);
    await userEvent.click(screen.getByRole("button", { name: "हिन्दी" }));
    await userEvent.click(screen.getByRole("button", { name: "बोलें" }));
    expect(instances).toHaveLength(1);
    expect(instances[0].lang).toBe("hi-IN");
    expect(instances[0].start).toHaveBeenCalled();
    act(() =>
      instances[0].onresult?.({
        results: {
          length: 1,
          0: { 0: { transcript: "मुझे फ्लैट चाहिए" }, isFinal: true },
        },
      }),
    );
    expect(screen.getByLabelText("आपका संदेश")).toHaveValue("मुझे फ्लैट चाहिए");
    // Nothing was sent: the visitor reads it and presses Send.
    act(() => instances[0].onend?.());
  });

  it("explains when the browser could not hear or does not know the language", async () => {
    const instances = fakeRecognition();
    render(<PublicChat />);
    await userEvent.click(screen.getByRole("button", { name: "తెలుగు" }));
    await userEvent.click(screen.getByRole("button", { name: "మాట్లాడండి" }));
    act(() => instances[0].onerror?.());
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "మీ గొంతు వినిపించలేదు",
    );
  });

  it("says who hears the voice before the microphone is used", () => {
    fakeRecognition();
    render(<PublicChat />);
    expect(
      screen.getByText(/may send your voice to its provider/),
    ).toBeInTheDocument();
  });

  describe("reading replies aloud", () => {
    function fakeSpeech() {
      const spoken: { text: string; lang: string }[] = [];
      const cancel = vi.fn();
      vi.stubGlobal("speechSynthesis", {
        speak: (u: { text: string; lang: string }) => spoken.push(u),
        cancel,
      });
      vi.stubGlobal(
        "SpeechSynthesisUtterance",
        class {
          lang = "";
          constructor(public text: string) {}
        },
      );
      return { spoken, cancel };
    }

    async function ask() {
      vi.spyOn(globalThis, "fetch").mockResolvedValue(
        reply(200, { reply: "जी, बताइए", lead_saved: false }),
      );
      await userEvent.type(screen.getByLabelText("आपका संदेश"), "नमस्ते");
      await userEvent.click(screen.getByRole("button", { name: "भेजें" }));
      await screen.findByText("जी, बताइए");
    }

    it("is off until the visitor asks for it", async () => {
      const { spoken } = fakeSpeech();
      render(<PublicChat />);
      await userEvent.click(screen.getByRole("button", { name: "हिन्दी" }));
      expect(screen.getByLabelText("जवाब बोलकर सुनाएँ")).not.toBeChecked();
      await ask();
      expect(spoken).toEqual([]);
    });

    it("reads the answer in the chosen language once it is switched on", async () => {
      const { spoken } = fakeSpeech();
      render(<PublicChat />);
      await userEvent.click(screen.getByRole("button", { name: "हिन्दी" }));
      await userEvent.click(screen.getByLabelText("जवाब बोलकर सुनाएँ"));
      await ask();
      expect(spoken).toHaveLength(1);
      expect(spoken[0]).toMatchObject({ text: "जी, बताइए", lang: "hi-IN" });
    });

    it("stops speaking when it is switched off", async () => {
      const { cancel } = fakeSpeech();
      render(<PublicChat />);
      const box = screen.getByLabelText("Read replies aloud");
      await userEvent.click(box);
      cancel.mockClear();
      await userEvent.click(box);
      expect(cancel).toHaveBeenCalled();
    });

    it("offers no read-aloud switch when the browser cannot speak", () => {
      render(<PublicChat />);
      expect(screen.queryByLabelText("Read replies aloud")).toBeNull();
    });
  });
});
