// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { updateDealRisk } from "@/app/(app)/deal-risk/actions";
import { DealRiskView } from "@/components/deal-risk-card";
import { UpdateDealRiskButton } from "@/components/deal-risk-button";
import { RiskBadge } from "@/components/risk-badge";
import { ApiError } from "@/lib/api-error";
import {
  dealRiskErrorText,
  isRiskLevel,
  levelChange,
  opportunityPath,
  riskByDeal,
  sumByCurrency,
  unknownText,
  type DealRisk,
} from "@/lib/deal-risk";
import { initialDialogState } from "@/lib/dialog-state";
import { canReadDealRisk } from "@/lib/permissions";

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

function risk(changes: Partial<DealRisk> = {}): DealRisk {
  return {
    id: "44444444-4444-4444-8444-444444444444",
    opportunity_id: DEAL,
    level: "high",
    score: 65,
    rules_version: 1,
    source: "nightly",
    computed_at: "2026-11-22T02:00:00Z",
    factors: [
      {
        code: "no_touch_30",
        sentence: "Nothing has happened on this deal for 40 days",
        points: 25,
        source: "activities",
      },
      {
        code: "close_date_passed",
        sentence: "The expected close date passed 10 days ago",
        points: 20,
        source: "deal",
      },
    ],
    unknown: ["account_health"],
    note: "Forecast: an estimate from the reasons listed, not a promise and not a probability.",
    deal: {
      id: DEAL,
      name: "Skyline",
      account_id: "22222222-2222-4222-8222-222222222222",
      stage: "negotiation",
      amount: "1200.50",
      currency: "INR",
    },
    ...changes,
  };
}

describe("permissions and levels", () => {
  it("shows risk only to people who hold deal_risk:read", () => {
    expect(canReadDealRisk({ permissions: ["deal_risk:read"] })).toBe(true);
    expect(canReadDealRisk({ permissions: ["deal_desk:run"] })).toBe(false);
    expect(canReadDealRisk({ permissions: [] })).toBe(false);
  });

  it("accepts only the three levels", () => {
    expect(isRiskLevel("high")).toBe(true);
    expect(isRiskLevel("extreme")).toBe(false);
    expect(isRiskLevel(undefined)).toBe(false);
  });

  it("writes the level out in words", () => {
    render(<RiskBadge level="medium" />);
    expect(screen.getByTestId("risk-badge").textContent).toBe("Medium risk");
  });
});

describe("the sums", () => {
  const deal = (amount: string | null, currency: string) =>
    ({ deal: { amount, currency } }) as never;

  it("adds amounts per currency exactly, without converting or weighting", () => {
    expect(
      sumByCurrency([
        deal("0.10", "INR"),
        deal("0.20", "INR"),
        deal("5", "EUR"),
        deal("1200.5", "INR"),
      ]),
    ).toEqual([
      { currency: "EUR", amount: "5.00" },
      { currency: "INR", amount: "1200.80" },
    ]);
  });

  it("skips deals without an amount or without a deal", () => {
    expect(sumByCurrency([deal(null, "INR"), { deal: null } as never])).toEqual(
      [],
    );
    expect(sumByCurrency([])).toEqual([]);
  });

  it("keeps the first forecast per deal", () => {
    const map = riskByDeal([risk({ level: "high" }), risk({ level: "low" })]);
    expect(Object.keys(map)).toEqual([DEAL]);
    expect(map[DEAL].level).toBe("high");
  });
});

describe("what changed", () => {
  it("says nothing when there is no earlier forecast", () => {
    expect(
      levelChange([{ level: "low", score: 1, computed_at: "x" }]),
    ).toBeNull();
  });

  it("reports a move and a no-change", () => {
    const now = {
      level: "high",
      score: 70,
      computed_at: "2026-11-22T02:00:00Z",
    };
    const before = {
      level: "medium",
      score: 40,
      computed_at: "2026-11-15T02:00:00Z",
    };
    expect(levelChange([now, before] as never)).toEqual({
      from: "medium",
      at: "2026-11-15T02:00:00Z",
      moved: true,
    });
    expect(
      levelChange([now, { ...before, level: "high" }] as never)?.moved,
    ).toBe(false);
  });
});

describe("words and links", () => {
  it("turns codes into plain words and keeps the API's own text otherwise", () => {
    expect(dealRiskErrorText("deal_risk_rate_limited", "x")).toMatch(
      /too many/,
    );
    expect(dealRiskErrorText("something_new", "The API's words")).toBe(
      "The API's words",
    );
    expect(unknownText("typical_stage_time")).toMatch(/too few won deals/);
    expect(unknownText("made_up_code")).toBe("made up code");
  });

  it("builds only a deal path from a well-formed id", () => {
    expect(opportunityPath(DEAL)).toBe(`/opportunities/${DEAL}`);
    expect(() => opportunityPath("../admin")).toThrow();
  });
});

describe("the forecast view", () => {
  it("lists every reason with its points, what is unknown and the estimate note", () => {
    render(<DealRiskView risk={risk()} history={[]} />);
    expect(screen.getByText("High risk")).toBeTruthy();
    expect(
      screen.getByText(/Nothing has happened on this deal for 40 days/),
    ).toBeTruthy();
    expect(
      screen.getByText(/expected close date passed 10 days ago/),
    ).toBeTruthy();
    expect(screen.getByText(/\(\+25, activities\)/)).toBeTruthy();
    expect(screen.getByText(/the customer account's health/)).toBeTruthy();
    expect(
      screen.getByText(/not a promise and not a probability/),
    ).toBeTruthy();
    expect(screen.getByText(/daily run/)).toBeTruthy();
  });

  it("says plainly when no warning signs were found", () => {
    render(
      <DealRiskView
        risk={risk({ level: "low", factors: [], unknown: [] })}
        history={[]}
      />,
    );
    expect(screen.getByText("No warning signs were found.")).toBeTruthy();
    expect(screen.queryByText(/Could not be read/)).toBeNull();
  });

  it("shows how the level moved since the earlier forecast", () => {
    render(
      <DealRiskView
        risk={risk()}
        history={[
          risk() as never,
          {
            ...risk(),
            level: "medium",
            computed_at: "2026-11-15T02:00:00Z",
          } as never,
        ]}
      />,
    );
    expect(screen.getByText(/It was medium risk on/)).toBeTruthy();
  });

  it("shows words a person wrote as plain text, never as HTML", () => {
    const { container } = render(
      <DealRiskView
        risk={risk({
          factors: [
            {
              code: "x",
              sentence: "<img src=x onerror=alert(1)>",
              points: 1,
              source: "deal",
            },
          ],
        })}
        history={[]}
      />,
    );
    expect(container.querySelector("img")).toBeNull();
    expect(screen.getByText(/<img src=x/)).toBeTruthy();
  });
});

describe("the button", () => {
  it("offers to work out a first forecast, or to update one", () => {
    const action = vi.fn(async () => initialDialogState);
    const { rerender } = render(
      <UpdateDealRiskButton action={action} hasForecast={false} />,
    );
    expect(
      screen.getByRole("button", { name: "Work out the forecast" }),
    ).toBeTruthy();
    rerender(<UpdateDealRiskButton action={action} hasForecast />);
    expect(
      screen.getByRole("button", { name: "Update forecast" }),
    ).toBeTruthy();
  });
});

describe("the server action", () => {
  beforeEach(() => {
    apiFetch.mockReset();
  });

  it("sends nothing but the deal in the path and goes back to the deal", async () => {
    apiFetch.mockResolvedValue({});
    await expect(updateDealRisk(DEAL, initialDialogState)).rejects.toThrow(
      `REDIRECT:/opportunities/${DEAL}?done=deal-risk-updated#deal-risk`,
    );
    const [path, init] = apiFetch.mock.calls[0];
    expect(path).toBe(`/deal-risk/${DEAL}/recompute`);
    expect(init).toEqual({ method: "POST" }); // no body: level and score are the server's
  });

  it("turns the limit into plain words and stays on the page", async () => {
    apiFetch.mockRejectedValue(
      new ApiError(429, {
        title: "Too many",
        detail: "x",
        code: "deal_risk_rate_limited",
      } as never),
    );
    const state = await updateDealRisk(DEAL, initialDialogState);
    expect(state.attempt).toBe(1);
    expect(state.error?.message).toMatch(/too many forecasts/);
  });

  it("refuses a tampered deal id before any request", async () => {
    await expect(updateDealRisk("../../x", initialDialogState)).rejects.toThrow(
      "invalid deal",
    );
    expect(apiFetch).not.toHaveBeenCalled();
  });
});
