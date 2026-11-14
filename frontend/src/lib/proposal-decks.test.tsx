import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { createProposalDeck } from "@/app/(app)/quotes/deck-actions";
import { StaffDeck } from "@/components/deck-views";
import { ApiError } from "@/lib/api-error";
import { initialDialogState } from "@/lib/dialog-state";
import {
  DECK_REFRESH_MS,
  deckErrorText,
  deckSize,
  deckStateText,
  isWorkingOnDeck,
  type DeckStatus,
} from "@/lib/proposal-decks";

const apiFetch = vi.fn();
vi.mock("@/lib/server/api", () => ({
  apiFetch: (...a: unknown[]) => apiFetch(...a),
}));
const refresh = vi.fn();
vi.mock("next/navigation", () => ({
  redirect: (to: string) => {
    throw new Error(`REDIRECT:${to}`);
  },
  useRouter: () => ({ refresh }),
}));

const QUOTE = "11111111-1111-4111-8111-111111111111";

function deck(over: Partial<DeckStatus> = {}): DeckStatus {
  return {
    status: "none",
    reason: null,
    file_name: null,
    size_bytes: null,
    created_at: null,
    refresh_failed: false,
    ...over,
  };
}

const READY = deck({
  status: "ready",
  file_name: "QT-0007-proposal.pdf",
  size_bytes: 84_000,
  created_at: "2026-11-13T09:00:00Z",
});

function problem(status: number, code: string) {
  return new ApiError(status, {
    title: "x",
    status,
    detail: "Server words",
    code,
    request_id: "r",
  });
}

beforeEach(() => {
  apiFetch.mockReset();
  refresh.mockReset();
});

describe("helpers", () => {
  it("each state has its own plain sentence", () => {
    expect(deckStateText(deck())).toBe("No deck yet.");
    expect(deckStateText(deck({ status: "queued" }))).toMatch(/being made/);
    expect(deckStateText(READY)).toBe("The deck is ready.");
    expect(deckStateText({ ...READY, refresh_failed: true })).toMatch(
      /earlier deck is still available/,
    );
    expect(deckStateText(deck({ status: "failed" }))).toMatch(
      /could not be made/,
    );
    expect(
      deckStateText(
        deck({
          status: "not_available",
          reason: "Replaced by a newer revision.",
        }),
      ),
    ).toBe("Replaced by a newer revision.");
    expect(deckStateText(deck({ status: "not_available" }))).toMatch(
      /once the quote is approved/,
    );
  });

  it("only a queued deck is work in progress", () => {
    expect(isWorkingOnDeck(deck({ status: "queued" }))).toBe(true);
    for (const status of ["none", "ready", "failed", "not_available"] as const)
      expect(isWorkingOnDeck(deck({ status }))).toBe(false);
  });

  it("the card looks again every few seconds, not in a tight loop", () => {
    expect(DECK_REFRESH_MS).toBeGreaterThanOrEqual(2000);
    expect(DECK_REFRESH_MS).toBeLessThanOrEqual(10_000);
  });

  it("sizes are written in plain words", () => {
    expect(deckSize(null)).toBe("");
    expect(deckSize(900)).toBe("900 B");
    expect(deckSize(84_000)).toBe("82 KB");
    expect(deckSize(3 * 1024 * 1024)).toBe("3.0 MB");
  });

  it("known error codes become sentences and others keep the server's words", () => {
    expect(deckErrorText("deck_pending", "x")).toMatch(/already being made/);
    expect(deckErrorText("quote_not_ready_for_deck", "x")).toMatch(
      /once the quote is approved/,
    );
    expect(deckErrorText("quote_superseded", "x")).toMatch(/newer revision/);
    expect(deckErrorText("deck_rate_limited", "x")).toMatch(/Too many/);
    expect(deckErrorText("forbidden", "x")).toMatch(/cannot make a deck/);
    expect(deckErrorText("other", "fallback")).toBe("fallback");
  });
});

describe("createProposalDeck", () => {
  it("posts to the quote's deck address with no body and goes back to the card", async () => {
    apiFetch.mockResolvedValueOnce({});
    await expect(createProposalDeck(QUOTE, initialDialogState)).rejects.toThrow(
      `REDIRECT:/quotes/${QUOTE}?done=deck-queued#deck`,
    );
    const [path, init] = apiFetch.mock.calls[0];
    expect(path).toBe(`/quotes/${QUOTE}/deck`);
    expect(init).toEqual({ method: "POST" });
  });

  it("refuses an id that is not an id before anything is sent", async () => {
    await expect(
      createProposalDeck("../x", initialDialogState),
    ).rejects.toThrow();
    expect(apiFetch).not.toHaveBeenCalled();
  });

  it("a refusal stays on the page, counts the attempt and explains in words", async () => {
    apiFetch.mockRejectedValueOnce(problem(409, "deck_pending"));
    const result = await createProposalDeck(QUOTE, initialDialogState);
    expect(result.attempt).toBe(1);
    expect(result.error?.message).toMatch(/already being made/);
  });
});

describe("StaffDeck", () => {
  const noop = vi.fn();

  function show(status: DeckStatus, canCreate = true, action = noop) {
    return render(
      <StaffDeck
        deck={status}
        downloadHref={`/quotes/${QUOTE}/deck`}
        canCreate={canCreate}
        action={action}
      />,
    );
  }

  it("with no deck it offers to create one and says what it uses", () => {
    show(deck());
    expect(screen.getByTestId("deck-state").textContent).toBe("No deck yet.");
    expect(
      screen.getByRole("button", { name: "Create proposal deck" }),
    ).toBeTruthy();
    expect(screen.getByText(/Uses your organisation's branding/)).toBeTruthy();
    expect(screen.queryByRole("link", { name: "Download deck" })).toBeNull();
  });

  it("a ready deck can be downloaded through the route handler and renewed", () => {
    show(READY);
    const link = screen.getByRole("link", { name: "Download deck" });
    expect(link.getAttribute("href")).toBe(`/quotes/${QUOTE}/deck`);
    expect(screen.getByText(/QT-0007-proposal\.pdf · 82 KB/)).toBeTruthy();
    expect(
      screen.getByRole("button", { name: "Make a new deck" }),
    ).toBeTruthy();
  });

  it("people who cannot change the quote can download but not create", () => {
    show(READY, false);
    expect(screen.getByRole("link", { name: "Download deck" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: /deck/i })).toBeNull();
  });

  it("an unavailable quote shows the reason and no button", () => {
    show(
      deck({
        status: "not_available",
        reason: "A proposal deck is available once the quote is approved.",
      }),
    );
    expect(screen.getByTestId("deck-state").textContent).toMatch(
      /once the quote is approved/,
    );
    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.queryByText(/Uses your organisation's branding/)).toBeNull();
  });

  it("a failed deck can be tried again", () => {
    show(deck({ status: "failed" }));
    expect(screen.getByTestId("deck-state").textContent).toMatch(
      /could not be made/,
    );
    expect(
      screen.getByRole("button", { name: "Create proposal deck" }),
    ).toBeTruthy();
  });

  it("while a deck is being made the button is disabled and the card says so", () => {
    show(deck({ status: "queued" }));
    expect(screen.getByRole("status").textContent).toMatch(/being made/);
    expect(
      (screen.getByRole("button", { name: "Making…" }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
  });

  it("pressing the button asks the server and shows its refusal in words", async () => {
    const action = vi.fn().mockResolvedValue({
      attempt: 1,
      fieldErrors: {},
      error: {
        code: "deck_pending",
        message: "A deck for this quote is already being made.",
        fieldErrors: {},
        requestId: "r",
        status: 409,
      },
    });
    show(deck(), true, action);
    await userEvent.click(
      screen.getByRole("button", { name: "Create proposal deck" }),
    );
    expect(action).toHaveBeenCalledTimes(1);
    expect((await screen.findByRole("alert")).textContent).toContain(
      "already being made",
    );
  });
});

describe("looking again while a deck is being made", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("refreshes the page every few seconds only while the deck is queued", () => {
    const { unmount } = render(
      <StaffDeck
        deck={deck({ status: "queued" })}
        downloadHref="/x"
        canCreate
        action={vi.fn()}
      />,
    );
    expect(refresh).not.toHaveBeenCalled();
    act(() => vi.advanceTimersByTime(DECK_REFRESH_MS));
    expect(refresh).toHaveBeenCalledTimes(1);
    act(() => vi.advanceTimersByTime(DECK_REFRESH_MS * 2));
    expect(refresh).toHaveBeenCalledTimes(3);
    unmount();
    act(() => vi.advanceTimersByTime(DECK_REFRESH_MS * 5));
    expect(refresh).toHaveBeenCalledTimes(3); // the timer stopped with the card
  });

  it("does not poll when nothing is being made", () => {
    render(
      <StaffDeck deck={READY} downloadHref="/x" canCreate action={vi.fn()} />,
    );
    act(() => vi.advanceTimersByTime(DECK_REFRESH_MS * 5));
    expect(refresh).not.toHaveBeenCalled();
  });
});
