import { render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { askStaffAssistant } from "@/app/(app)/assistant/actions";
import { initialStaffAssistantState } from "@/app/(app)/assistant/state";
import { AssistantProposals } from "@/components/approval-views";
import { apiFetch } from "@/lib/server/api";

vi.mock("@/lib/server/api", () => ({ apiFetch: vi.fn() }));

const PROPOSAL = {
  id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
  description: "Change the lead's status to contacted",
  status: "pending",
  link: "/approvals/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
};

describe("AssistantProposals", () => {
  it("lists what the assistant proposed and says nothing has changed yet", () => {
    render(<AssistantProposals proposals={[PROPOSAL]} />);
    const region = screen.getByRole("region", { name: "Waiting for approval" });
    expect(
      within(region).getByText(/nothing has changed yet/i),
    ).toBeInTheDocument();
    const link = within(region).getByRole("link", {
      name: "Change the lead's status to contacted",
    });
    expect(link).toHaveAttribute("href", PROPOSAL.link);
  });

  it("shows proposals as plain text", () => {
    const { container } = render(
      <AssistantProposals
        proposals={[{ ...PROPOSAL, description: "<img src=x> Hello" }]}
      />,
    );
    expect(container.querySelector("img")).toBeNull();
    expect(screen.getByText(/<img src=x> Hello/)).toBeInTheDocument();
  });

  it("is left out when there are none", () => {
    const { container } = render(<AssistantProposals proposals={[]} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("askStaffAssistant", () => {
  beforeEach(() => {
    vi.mocked(apiFetch).mockReset(); // no return value: Vitest would run it as a cleanup
  });

  function question(text: string) {
    const data = new FormData();
    data.set("question", text);
    return data;
  }

  it("passes the proposals of the answer on", async () => {
    vi.mocked(apiFetch).mockResolvedValue({
      answer: "I proposed it.",
      links: ["/approvals/x"],
      proposals: [PROPOSAL],
    });
    const state = await askStaffAssistant(
      initialStaffAssistantState,
      question("Mark Asha Rao as contacted"),
    );
    expect(state.error).toBeNull();
    expect(state.answer).toBe("I proposed it.");
    expect(state.proposals).toEqual([PROPOSAL]);
  });

  it("copes with an answer without proposals", async () => {
    vi.mocked(apiFetch).mockResolvedValue({ answer: "Fine.", links: [] });
    const state = await askStaffAssistant(
      initialStaffAssistantState,
      question("How are you?"),
    );
    expect(state.proposals).toEqual([]);
  });

  it("clears the old proposals when the next question fails", async () => {
    vi.mocked(apiFetch).mockRejectedValue(new Error("down"));
    const state = await askStaffAssistant(
      { ...initialStaffAssistantState, proposals: [PROPOSAL] },
      question("Again please"),
    );
    expect(state.error).not.toBeNull();
    expect(state.proposals).toEqual([]);
  });
});
