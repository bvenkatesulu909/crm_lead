// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { askDealRiskCoach } from "@/app/(app)/deal-risk/actions";
import {
  DealRiskCoachButton,
  DealRiskCoachView,
} from "@/components/deal-risk-coach";
import { ApiError } from "@/lib/api-error";
import {
  coachErrorText,
  coachProposalLink,
  initialCoachState,
  type DealRiskCoach,
} from "@/lib/deal-risk";

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
const PROPOSAL = "33333333-3333-4333-8333-333333333333";

function coach(changes: Partial<DealRiskCoach> = {}): DealRiskCoach {
  return {
    opportunity_id: DEAL,
    advice: [
      {
        text: "Agree a next step with the buyer.",
        factors: ["nothing_planned"],
      },
    ],
    proposals: [{ id: PROPOSAL, link: `/approvals/${PROPOSAL}` }],
    blocked_messages: [],
    cleaned: false,
    note: "AI advice on the forecast. It changes nothing; any suggested task waits for a different person to approve it.",
    ...changes,
  };
}

describe("words and links", () => {
  it("turns the coach's codes into plain words", () => {
    expect(coachErrorText("agent_unavailable", "x")).toMatch(/switched off/);
    expect(coachErrorText("deal_risk_coach_rate_limited", "x")).toMatch(
      /an hour/,
    );
    expect(coachErrorText("deal_risk_coach_invalid_answer", "x")).toMatch(
      /Nothing was shown/,
    );
    expect(coachErrorText("something_new", "The API's words")).toBe(
      "The API's words",
    );
  });

  it("links a suggested task only into the approval queue", () => {
    expect(coachProposalLink(`/approvals/${PROPOSAL}`)).toBe(
      `/approvals/${PROPOSAL}`,
    );
    expect(coachProposalLink("https://evil.example/approvals/x")).toBeNull();
    expect(coachProposalLink("/approvals/../admin")).toBeNull();
  });
});

describe("the advice view", () => {
  it("shows the advice, the suggested task link and the note", () => {
    render(<DealRiskCoachView result={coach()} />);
    expect(screen.getByText("Agree a next step with the buyer.")).toBeTruthy();
    const link = screen.getByRole("link", { name: "Suggested task 1" });
    expect(link.getAttribute("href")).toBe(`/approvals/${PROPOSAL}`);
    expect(screen.getByText(/changes nothing/)).toBeTruthy();
  });

  it("says so when there is no advice, and when text was cleaned or a task was stopped", () => {
    render(
      <DealRiskCoachView
        result={coach({
          advice: [],
          proposals: [],
          cleaned: true,
          blocked_messages: ["x"],
        })}
      />,
    );
    expect(
      screen.getByText("The coach had no advice for this deal."),
    ).toBeTruthy();
    expect(screen.getByText(/was cleaned/)).toBeTruthy();
    expect(screen.getByText(/stopped 1 suggested task\./)).toBeTruthy();
    expect(screen.queryByRole("link")).toBeNull();
  });

  it("shows what the model wrote as plain text, never as HTML", () => {
    const { container } = render(
      <DealRiskCoachView
        result={coach({
          advice: [{ text: "<img src=x onerror=alert(1)>", factors: ["x"] }],
        })}
      />,
    );
    expect(container.querySelector("img")).toBeNull();
    expect(screen.getByText(/<img src=x/)).toBeTruthy();
  });

  it("drops a suggested task whose link is not into the approval queue", () => {
    render(
      <DealRiskCoachView
        result={coach({
          proposals: [{ id: PROPOSAL, link: "https://evil.example" }],
        })}
      />,
    );
    expect(screen.queryByRole("link")).toBeNull();
  });
});

describe("the button", () => {
  it("offers to ask the coach and shows nothing else before it is pressed", () => {
    render(
      <DealRiskCoachButton action={vi.fn(async () => initialCoachState)} />,
    );
    expect(
      screen.getByRole("button", { name: "Ask the AI coach" }),
    ).toBeTruthy();
    expect(screen.queryByTestId("coach-advice")).toBeNull();
  });
});

describe("the server action", () => {
  beforeEach(() => {
    apiFetch.mockReset();
  });

  it("sends nothing but the deal and hands the advice back to the screen", async () => {
    apiFetch.mockResolvedValue(coach());
    const state = await askDealRiskCoach(DEAL, initialCoachState);
    const [path, init] = apiFetch.mock.calls[0];
    expect(path).toBe(`/deal-risk/${DEAL}/coach`);
    expect(init.method).toBe("POST");
    expect(init.body).toBeUndefined(); // no advice or tasks from the browser
    expect(state).toEqual({ attempt: 1, result: coach(), error: null });
  });

  it("turns a switched-off coach into plain words and shows no advice", async () => {
    apiFetch.mockRejectedValue(
      new ApiError(503, {
        title: "Off",
        detail: "off",
        code: "agent_unavailable",
      } as never),
    );
    const state = await askDealRiskCoach(DEAL, initialCoachState);
    expect(state.result).toBeNull();
    expect(state.error?.message).toMatch(/switched off/);
  });

  it("refuses a tampered deal id before any request", async () => {
    await expect(askDealRiskCoach("../x", initialCoachState)).rejects.toThrow(
      "invalid deal",
    );
    expect(apiFetch).not.toHaveBeenCalled();
  });
});
