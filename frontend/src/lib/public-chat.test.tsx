import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ChatTranscriptCard } from "@/components/chat-transcript-card";
import type { PublicChatTranscript } from "@/lib/api-types";

const transcript: PublicChatTranscript = {
  started_at: "2026-10-25T09:00:00Z",
  messages: [
    { role: "visitor", content: "Hi, I want a 3BHK", created_at: "2026-10-25T09:00:00Z" },
    {
      role: "assistant",
      content: "Happy to help! May I have your name and phone number?",
      created_at: "2026-10-25T09:00:02Z",
    },
    {
      role: "visitor",
      content: "Suresh Kumar, 98480 12345\n<b>not bold</b>",
      created_at: "2026-10-25T09:01:00Z",
    },
  ],
};

describe("ChatTranscriptCard", () => {
  it("shows every message in order, labelled by who wrote it", () => {
    render(<ChatTranscriptCard transcript={transcript} />);
    const card = screen.getByRole("region", { name: "Website chat" });
    const items = within(card).getAllByRole("listitem");
    expect(items).toHaveLength(3);
    expect(items[0]).toHaveTextContent("Visitor");
    expect(items[0]).toHaveTextContent("Hi, I want a 3BHK");
    expect(items[1]).toHaveTextContent("Assistant");
    expect(within(card).getByText(/3 messages/)).toBeInTheDocument();
  });

  it("shows what the visitor typed as plain text, never as HTML", () => {
    const { container } = render(<ChatTranscriptCard transcript={transcript} />);
    expect(container.querySelector("b")).toBeNull();
    expect(screen.getByText(/<b>not bold<\/b>/)).toBeInTheDocument();
  });

  it("shows nothing for a lead that did not come from the chat", () => {
    const { container } = render(
      <ChatTranscriptCard transcript={{ started_at: null, messages: [] }} />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});
