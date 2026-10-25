import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { PublicChat } from "@/components/public-chat";
import { chatErrorText, checkVisitorMessage } from "@/lib/public-chat";
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
    expect(JSON.parse(init.body)).toEqual({ message: "Hello", website: "" });
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
