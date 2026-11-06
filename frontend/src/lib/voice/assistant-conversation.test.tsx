import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AssistantConversation } from "@/components/assistant-conversation";
import type { VoiceStatus } from "@/lib/voice/choose";

const ID = "11111111-2222-4333-8444-555555555555";

function sse(...events: [string, unknown][]): string {
  return events
    .map(([name, data]) => `event: ${name}\ndata: ${JSON.stringify(data)}\n\n`)
    .join("");
}

function mockApi(turnBody: string | { status: number; body: unknown }) {
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === "/assistant/conversations") return Response.json({ id: ID });
    if (url === `/assistant/conversations/${ID}/turns`) {
      if (typeof turnBody === "string")
        return new Response(turnBody, {
          headers: { "Content-Type": "text/event-stream" },
        });
      return Response.json(turnBody.body, { status: turnBody.status });
    }
    throw new Error(`unexpected ${url} ${init?.method}`);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

const on: VoiceStatus = {
  enabled: true,
  browser_engine: true,
  server_engine: false,
  minutes_used: 0,
  minutes_budget: 300,
};

afterEach(() => vi.unstubAllGlobals());

describe("talking with the assistant", () => {
  it("streams a typed question's answer and shows proposals waiting for approval", async () => {
    const fetchMock = mockApi(
      sse(
        ["sentence", { text: "I proposed it." }],
        ["sentence", { text: "A manager decides." }],
        [
          "done",
          {
            answer: "I proposed it. A manager decides.",
            ticket_id: "t",
            links: [],
            proposals: [
              {
                id: "p1",
                description: "Set lead to contacted",
                status: "pending",
                link: "/approvals/p1",
              },
            ],
          },
        ],
      ),
    );
    const user = userEvent.setup();
    render(<AssistantConversation voice={null} />);
    await user.type(
      screen.getByLabelText("Your question"),
      "Mark Asha as contacted{Enter}",
    );
    expect(
      await screen.findByText("I proposed it. A manager decides."),
    ).toBeInTheDocument();
    expect(screen.getByText("Mark Asha as contacted")).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Set lead to contacted" }),
    ).toHaveAttribute("href", "/approvals/p1");
    // Only the question and the mode are sent - never a history or an identity.
    const body = JSON.parse(String(fetchMock.mock.calls[1][1]?.body));
    expect(body).toEqual({ question: "Mark Asha as contacted", mode: "text" });
  });

  it("shows what the model wrote as plain text, never as HTML", async () => {
    mockApi(
      sse([
        "done",
        {
          answer: '<img src="x" onerror="alert(1)"> hi',
          ticket_id: "t",
          links: [],
          proposals: [],
        },
      ]),
    );
    const user = userEvent.setup();
    const { container } = render(<AssistantConversation voice={null} />);
    await user.type(screen.getByLabelText("Your question"), "hi{Enter}");
    expect(await screen.findByText(/onerror/)).toBeInTheDocument();
    expect(container.querySelector("img")).toBeNull();
  });

  it("explains a refusal in plain words and keeps the question", async () => {
    mockApi({
      status: 503,
      body: { code: "agent_unavailable", detail: "off" },
    });
    const user = userEvent.setup();
    render(<AssistantConversation voice={null} />);
    await user.type(screen.getByLabelText("Your question"), "hello{Enter}");
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "switched off for your organisation",
    );
    expect(screen.getByLabelText("Your question")).toHaveValue("hello");
  });

  it("an error in the middle of the stream drops the half answer", async () => {
    mockApi(
      sse(
        ["sentence", { text: "Half" }],
        ["error", { code: "assistant_unavailable", detail: "x" }],
      ),
    );
    const user = userEvent.setup();
    render(<AssistantConversation voice={null} />);
    await user.type(screen.getByLabelText("Your question"), "hello{Enter}");
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "could not answer",
    );
    expect(screen.queryByText("Half")).toBeNull();
  });

  it("offers no voice while it is switched off", () => {
    render(<AssistantConversation voice={{ ...on, enabled: false }} />);
    expect(
      screen.queryByRole("button", { name: /voice|microphone/i }),
    ).toBeNull();
  });

  it("says when this browser cannot listen", () => {
    // jsdom has no SpeechRecognition, like Firefox.
    render(<AssistantConversation voice={on} />);
    expect(screen.getByText(/This browser cannot listen/)).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Allow microphone/ }),
    ).toBeNull();
  });

  it("names who hears the audio before the microphone is first used", () => {
    class FakeRecognition {}
    vi.stubGlobal("webkitSpeechRecognition", FakeRecognition);
    vi.stubGlobal("speechSynthesis", {
      speak: vi.fn(),
      cancel: vi.fn(),
      getVoices: () => [],
    });
    render(<AssistantConversation voice={on} />);
    expect(
      screen.getByText(/Google in Chrome, Apple in Safari, Microsoft in Edge/),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Allow microphone and start" }),
    ).toBeInTheDocument();
  });
});
