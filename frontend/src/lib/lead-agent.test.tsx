// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { AskLeadAgentButton } from "@/components/lead-agent-card";
import { LeadAgentSection } from "@/components/lead-agent-section";
import { leadAgentErrorText, outcomeDone } from "@/lib/lead-agent";

const apiFetch = vi.fn();
vi.mock("@/lib/server/api", () => ({
  apiFetch: (...a: unknown[]) => apiFetch(...a),
}));
vi.mock("next/navigation", () => ({
  redirect: (to: string) => {
    throw new Error(`REDIRECT:${to}`);
  },
}));

const LEAD = "11111111-1111-4111-8111-111111111111";

describe("plain words", () => {
  it("says an off agent is off and where to switch it on", () => {
    expect(leadAgentErrorText("agent_unavailable", "x")).toContain(
      "switched off",
    );
  });
  it("keeps the API's own words for a code it has no wording for", () => {
    expect(leadAgentErrorText("lead_agent_rate_limited", "Try later.")).toBe(
      "Try later.",
    );
    expect(leadAgentErrorText(undefined, "Plain.")).toBe("Plain.");
  });
  it("maps each outcome to a message on the lead page", () => {
    expect(outcomeDone("proposed")).toBe("lead-agent-proposed");
    expect(outcomeDone("no_suggestion")).toBe("lead-agent-nothing");
    expect(outcomeDone("blocked")).toBe("lead-agent-blocked");
    expect(outcomeDone("something-new")).toBe("lead-agent-nothing");
  });
});

describe("the button", () => {
  it("shows the server's words when the agent is switched off", async () => {
    const action = vi.fn(async () => ({
      attempt: 1,
      fieldErrors: {},
      error: {
        title: "x",
        status: 503,
        message: "The lead agent is switched off.",
        code: "agent_unavailable",
        fieldErrors: {},
        requestId: null,
      },
    }));
    render(<AskLeadAgentButton action={action} />);
    fireEvent.click(screen.getByRole("button", { name: "Ask the lead agent" }));
    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent("switched off"),
    );
    expect(
      screen.getByText(/Nothing changes until a different person approves/),
    ).toBeInTheDocument();
  });
});

describe("the card", () => {
  it("is shown to people who may run the Qualifier and to nobody else", () => {
    const { container, rerender } = render(
      <LeadAgentSection
        me={{ permissions: ["qualifier:run"] }}
        leadId={LEAD}
      />,
    );
    expect(screen.getByText("Lead agent")).toBeInTheDocument();
    rerender(
      <LeadAgentSection
        me={{ permissions: ["lead:read:own"] }}
        leadId={LEAD}
      />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});
