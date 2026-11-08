// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { researchAccount } from "@/app/(app)/deal-desk/research-actions";
import { AccountBriefView } from "@/components/account-research-card";
import { ApiError } from "@/lib/api-error";
import {
  accountPath,
  researchErrorText,
  type AccountBrief,
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

const ACCOUNT = "11111111-1111-4111-8111-111111111111";
const DEAL = "22222222-2222-4222-8222-222222222222";

function brief(changes: Partial<AccountBrief> = {}): AccountBrief {
  return {
    id: "33333333-3333-4333-8333-333333333333",
    account_id: ACCOUNT,
    created_at: "2026-11-08T10:00:00Z",
    sentences: [
      {
        text: "One open deal in proposal.",
        records: [{ type: "opportunity", id: DEAL }],
      },
      {
        text: "Customer health is watch.",
        records: [{ type: "account", id: ACCOUNT }],
      },
    ],
    dropped: 0,
    gathered: { sales: 2, service: 1, conversations: 2, registry: 1 },
    ...changes,
  };
}

describe("the brief", () => {
  it("shows each sentence and links the deal it names, not the account itself", () => {
    render(<AccountBriefView brief={brief()} />);
    expect(screen.getByText("One open deal in proposal.")).toBeTruthy();
    expect(
      screen.getByRole("link", { name: "Open deal" }).getAttribute("href"),
    ).toBe(`/opportunities/${DEAL}`);
    expect(screen.getAllByRole("link")).toHaveLength(1);
    expect(screen.queryByText(/left out/)).toBeNull();
  });

  it("says when sentences without a source were left out", () => {
    render(<AccountBriefView brief={brief({ dropped: 2 })} />);
    expect(screen.getByText(/2 sentence\(s\) were left out/)).toBeTruthy();
  });

  it("shows model text as plain text and links no made-up record", () => {
    const { container } = render(
      <AccountBriefView
        brief={brief({
          sentences: [
            {
              text: "<img src=x onerror=alert(1)>",
              records: [{ type: "opportunity", id: "https://evil.example" }],
            },
          ],
        })}
      />,
    );
    expect(container.querySelector("img")).toBeNull();
    expect(screen.queryByRole("link")).toBeNull();
  });
});

describe("plain words", () => {
  it("names the switch and keeps the API's own words otherwise", () => {
    expect(researchErrorText("agent_unavailable", "x")).toContain("AI agents");
    expect(researchErrorText("account_research_rate_limited", "Later.")).toBe(
      "Later.",
    );
    expect(accountPath(ACCOUNT)).toBe(`/accounts/${ACCOUNT}`);
    expect(() => accountPath("../x")).toThrow();
  });
});

describe("the server action", () => {
  beforeEach(() => {
    apiFetch.mockReset(); // no return value: Vitest would run it as a cleanup
  });

  it("sends only the account, waits long enough and goes back", async () => {
    apiFetch.mockResolvedValue({});
    await expect(researchAccount(ACCOUNT, initialDialogState)).rejects.toThrow(
      `REDIRECT:/accounts/${ACCOUNT}?done=account-researched#account-research`,
    );
    const [path, init] = apiFetch.mock.calls[0];
    expect(path).toBe("/account-research/briefs");
    expect(JSON.parse(init.body)).toEqual({ account_id: ACCOUNT });
    expect(init.signal).toBeInstanceOf(AbortSignal);
  });

  it("turns a refusal into plain words", async () => {
    apiFetch.mockRejectedValue(
      new ApiError(503, {
        title: "x",
        detail: "off",
        code: "agent_unavailable",
      } as never),
    );
    const state = await researchAccount(ACCOUNT, initialDialogState);
    expect(state.error?.message).toContain("switched off");
  });

  it("refuses a tampered id before calling the API", async () => {
    await expect(
      researchAccount("../admin", initialDialogState),
    ).rejects.toThrow();
    expect(apiFetch).not.toHaveBeenCalled();
  });
});
