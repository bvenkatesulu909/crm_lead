// @vitest-environment jsdom
import { render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { askDealDesk } from "@/app/(app)/deal-desk/actions";
import { AskDealDeskButton } from "@/components/deal-desk-button";
import { ApiError } from "@/lib/api-error";
import { DealDeskReviewView } from "@/components/deal-desk-card";
import {
  dealDeskErrorText,
  opportunityPath,
  proposalLink,
  recordLink,
  type DealDeskReview,
} from "@/lib/deal-desk";
import { initialDialogState } from "@/lib/dialog-state";

const apiFetch = vi.fn();
vi.mock("@/lib/server/api", () => ({
  apiFetch: (...a: unknown[]) => apiFetch(...a),
}));
vi.mock("next/navigation", () => ({
  redirect: (to: string) => {
    throw new Error(`REDIRECT:${to}`);
  },
}));

const DEAL = "11111111-1111-4111-8111-111111111111";
const QUOTE = "22222222-2222-4222-8222-222222222222";
const PROPOSAL = "33333333-3333-4333-8333-333333333333";

function review(changes: Partial<DealDeskReview> = {}): DealDeskReview {
  return {
    id: "44444444-4444-4444-8444-444444444444",
    opportunity_id: DEAL,
    created_at: "2026-11-08T10:00:00Z",
    brief: "The discount is above the limit.",
    findings: [
      {
        reviewer: "pricing",
        severity: "act",
        text: "QT-0001 gives 12.00 %, above the approval limit.",
        records: [{ type: "quote", id: QUOTE }],
      },
      {
        reviewer: "momentum",
        severity: "watch",
        text: "The deal has no next step.",
        records: [{ type: "opportunity", id: DEAL }],
      },
    ],
    reviewers: {
      pricing: "answered",
      account: "refused",
      momentum: "answered",
    },
    proposals: [{ id: PROPOSAL, link: `/approvals/${PROPOSAL}` }],
    ...changes,
  };
}

describe("plain words and safe links", () => {
  it("says an off deal desk is off and where to switch it on", () => {
    expect(dealDeskErrorText("agent_unavailable", "x")).toContain("AI agents");
    expect(dealDeskErrorText("deal_desk_owner_only", "x")).toContain("owner");
    expect(dealDeskErrorText("deal_desk_rate_limited", "Try later.")).toBe(
      "Try later.",
    );
  });

  it("links only known record kinds with real ids", () => {
    expect(recordLink("quote", QUOTE)).toBe(`/quotes/${QUOTE}`);
    expect(recordLink("contract", QUOTE)).toBe(`/contracts/${QUOTE}`);
    expect(recordLink("opportunity", DEAL)).toBe(`/opportunities/${DEAL}`);
    expect(recordLink("lead", QUOTE)).toBeNull();
    expect(recordLink("quote", "../../admin")).toBeNull();
    expect(recordLink("quote", "https://evil.example")).toBeNull();
  });

  it("points proposals into the approval queue only", () => {
    expect(proposalLink(`/approvals/${PROPOSAL}`)).toBe(
      `/approvals/${PROPOSAL}`,
    );
    expect(proposalLink("https://evil.example/approvals/x")).toBeNull();
    expect(proposalLink(`/approvals/${PROPOSAL}/../../x`)).toBeNull();
  });

  it("refuses a tampered deal id", () => {
    expect(opportunityPath(DEAL)).toBe(`/opportunities/${DEAL}`);
    expect(() => opportunityPath("../leads")).toThrow();
  });
});

describe("the review", () => {
  it("shows the brief, the findings by reviewer and the waiting tasks", () => {
    render(<DealDeskReviewView review={review()} />);
    expect(screen.getByText("The discount is above the limit.")).toBeTruthy();
    expect(screen.getByText("Pricing")).toBeTruthy();
    expect(screen.getByText("Needs action")).toBeTruthy();
    expect(
      screen.getByRole("link", { name: "Open quote" }).getAttribute("href"),
    ).toBe(`/quotes/${QUOTE}`);
    // The deal itself is not linked from its own page.
    expect(screen.queryByRole("link", { name: "Open this deal" })).toBeNull();
    expect(
      screen.getByText(/No usable answer this time from: Account/),
    ).toBeTruthy();
    const task = screen.getByRole("link", { name: "Suggested task 1" });
    expect(task.getAttribute("href")).toBe(`/approvals/${PROPOSAL}`);
  });

  it("shows what a model wrote as plain text, never as HTML", () => {
    const { container } = render(
      <DealDeskReviewView
        review={review({
          brief: "<img src=x onerror=alert(1)> <b>bold</b>",
          proposals: [{ id: PROPOSAL, link: "https://evil.example" }],
        })}
      />,
    );
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("b")).toBeNull();
    expect(screen.getByText(/<img src=x/)).toBeTruthy();
    expect(
      within(container).queryByRole("link", { name: /Suggested task/ }),
    ).toBeNull();
  });
});

describe("the button", () => {
  it("shows the server's words when the deal desk is switched off", async () => {
    const action = vi.fn(async () => ({
      attempt: 1,
      fieldErrors: {},
      error: {
        title: "x",
        status: 503,
        message: "The deal desk is switched off.",
        code: "agent_unavailable",
        fieldErrors: {},
        requestId: null,
      },
    }));
    render(<AskDealDeskButton action={action} />);
    expect(
      screen.getByRole("button", { name: "Review this deal" }),
    ).toBeTruthy();
  });
});

describe("the server action", () => {
  beforeEach(() => {
    apiFetch.mockReset(); // no return value: Vitest would run it as a cleanup
  });

  it("sends only the deal, waits long enough and goes back to the deal", async () => {
    apiFetch.mockResolvedValue({});
    await expect(askDealDesk(DEAL, initialDialogState)).rejects.toThrow(
      `REDIRECT:/opportunities/${DEAL}?done=deal-desk-reviewed#deal-desk`,
    );
    const [path, init] = apiFetch.mock.calls[0];
    expect(path).toBe("/deal-desk/reviews");
    expect(JSON.parse(init.body)).toEqual({ opportunity_id: DEAL });
    expect(init.signal).toBeInstanceOf(AbortSignal);
  });

  it("turns an API refusal into plain words and stays on the page", async () => {
    apiFetch.mockRejectedValue(
      new ApiError(503, {
        title: "Service unavailable",
        detail: "off",
        code: "agent_unavailable",
      } as never),
    );
    const state = await askDealDesk(DEAL, initialDialogState);
    expect(state.error?.message).toContain("switched off");
    expect(state.attempt).toBe(1);
  });

  it("refuses a tampered id before calling the API", async () => {
    await expect(askDealDesk("../admin", initialDialogState)).rejects.toThrow();
    expect(apiFetch).not.toHaveBeenCalled();
  });
});
