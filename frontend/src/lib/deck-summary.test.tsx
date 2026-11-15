import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { draftDeckSummary } from "@/app/(app)/quotes/deck-actions";
import { SummaryBlock } from "@/components/deck-views";
import { ApiError } from "@/lib/api-error";
import { initialDialogState } from "@/lib/dialog-state";
import { summaryErrorText } from "@/lib/proposal-decks";

const apiFetch = vi.fn();
vi.mock("@/lib/server/api", () => ({
  apiFetch: (...a: unknown[]) => apiFetch(...a),
}));
vi.mock("next/navigation", () => ({
  redirect: (to: string) => {
    throw new Error(`REDIRECT:${to}`);
  },
  useRouter: () => ({ refresh: vi.fn() }),
}));

const QUOTE = "11111111-1111-4111-8111-111111111111";
const PROPOSAL = "22222222-2222-4222-8222-222222222222";

function problem(status: number, code: string) {
  return new ApiError(status, {
    title: "x",
    status,
    detail: "Server words",
    code,
    request_id: "r",
  });
}

beforeEach(() => apiFetch.mockReset());

describe("summaryErrorText", () => {
  it("explains the known refusals in plain words", () => {
    expect(summaryErrorText("agent_unavailable", "x")).toMatch(
      /switched off.*AI agents/,
    );
    expect(summaryErrorText("agent_budget_reached", "x")).toMatch(/budget/);
    expect(summaryErrorText("deck_writer_rate_limited", "x")).toMatch(
      /moment ago/,
    );
    expect(summaryErrorText("deck_writer_invalid_answer", "x")).toMatch(
      /could not be used/,
    );
    expect(summaryErrorText("agent_action_limit_reached", "x")).toMatch(
      /too many proposals/,
    );
    expect(summaryErrorText("quote_not_ready_for_deck", "x")).toMatch(
      /once the quote is approved/,
    );
    expect(summaryErrorText("quote_superseded", "x")).toMatch(/newer revision/);
    expect(summaryErrorText("forbidden", "x")).toMatch(/cannot/);
  });

  it("keeps the server's words for anything else", () => {
    expect(summaryErrorText("other", "fallback")).toBe("fallback");
    expect(summaryErrorText(null, "fallback")).toBe("fallback");
  });
});

describe("draftDeckSummary", () => {
  it("asks the writer with no body and opens the proposal that waits", async () => {
    apiFetch.mockResolvedValueOnce({
      outcome: "proposed",
      proposal_id: PROPOSAL,
      proposal_link: `/approvals/${PROPOSAL}`,
      blocked_message: null,
    });
    await expect(draftDeckSummary(QUOTE, initialDialogState)).rejects.toThrow(
      `REDIRECT:/approvals/${PROPOSAL}`,
    );
    const [path, init] = apiFetch.mock.calls[0];
    expect(path).toBe(`/quotes/${QUOTE}/deck/summary-draft`);
    expect(init).toEqual({ method: "POST" });
  });

  it("refuses an id that is not an id before anything is sent", async () => {
    await expect(
      draftDeckSummary("../x", initialDialogState),
    ).rejects.toThrow();
    expect(apiFetch).not.toHaveBeenCalled();
  });

  it("shows the safety check's reason when the text was blocked", async () => {
    apiFetch.mockResolvedValueOnce({
      outcome: "blocked",
      proposal_id: null,
      proposal_link: null,
      blocked_message: "The text contains a link.",
    });
    const result = await draftDeckSummary(QUOTE, initialDialogState);
    expect(result.attempt).toBe(1);
    expect(result.error?.message).toMatch(/blocked/i);
    expect(result.error?.message).toContain("The text contains a link.");
  });

  it("does not follow an id the server sends that is not an id", async () => {
    apiFetch.mockResolvedValueOnce({
      outcome: "proposed",
      proposal_id: "../../evil",
      proposal_link: "https://evil.example",
      blocked_message: null,
    });
    await expect(draftDeckSummary(QUOTE, initialDialogState)).rejects.toThrow(
      "invalid proposal id",
    );
  });

  it("explains a refusal in words and counts the attempt", async () => {
    apiFetch.mockRejectedValueOnce(problem(503, "agent_unavailable"));
    const result = await draftDeckSummary(QUOTE, initialDialogState);
    expect(result.attempt).toBe(1);
    expect(result.error?.message).toMatch(/switched off/);
  });
});

describe("SummaryBlock", () => {
  const noop = vi.fn();

  function show(summary: string | null, canDraft = true, action = noop) {
    return render(
      <SummaryBlock summary={summary} canDraft={canDraft} action={action} />,
    );
  }

  it("with no text yet it says so and offers a draft", () => {
    show(null);
    expect(screen.getByTestId("deck-summary").textContent).toBe(
      "No summary slide yet.",
    );
    expect(
      screen.getByRole("button", { name: "Draft with the deck writer" }),
    ).toBeTruthy();
    expect(screen.getByText(/different person approves/i)).toBeTruthy();
  });

  it("shows the approved text as plain text, never as markup", () => {
    show('A <b>bold</b> & "quoted" claim');
    expect(screen.getByTestId("deck-summary").textContent).toBe(
      'A <b>bold</b> & "quoted" claim',
    );
    expect(document.querySelector("b")).toBeNull();
    expect(
      screen.getByRole("button", { name: "Draft a new one" }),
    ).toBeTruthy();
  });

  it("people who cannot change the quote see the text but no button", () => {
    show("Approved text.", false);
    expect(screen.getByTestId("deck-summary").textContent).toBe(
      "Approved text.",
    );
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("pressing the button asks the server and shows its refusal in words", async () => {
    const action = vi.fn().mockResolvedValue({
      attempt: 1,
      fieldErrors: {},
      error: {
        code: "agent_unavailable",
        message: "The deck writer is switched off.",
        fieldErrors: {},
        requestId: "r",
        status: 503,
      },
    });
    show(null, true, action);
    await userEvent.click(
      screen.getByRole("button", { name: "Draft with the deck writer" }),
    );
    expect(action).toHaveBeenCalledTimes(1);
    expect((await screen.findByRole("alert")).textContent).toContain(
      "switched off",
    );
  });
});
