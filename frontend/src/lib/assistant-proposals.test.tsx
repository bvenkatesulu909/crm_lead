import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AssistantProposals } from "@/components/approval-views";

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
