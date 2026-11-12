import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import {
  addMemory,
  confirmMemory,
  copyMemoryFromLead,
} from "@/app/(app)/leads/[id]/memory-actions";
import { BuyerMemoryView } from "@/components/buyer-memory-views";
import { ApiError } from "@/lib/api-error";
import type { BuyerMemory, BuyerMemoryItem } from "@/lib/api-types";
import {
  checkConfirm,
  checkNewMemory,
  groupMemory,
  memoryErrorText,
  memorySummary,
  sourceLabel,
} from "@/lib/buyer-memory";
import { initialDialogState, type DialogState } from "@/lib/dialog-state";
import { canReadBuyerMemory, canWriteBuyerMemory } from "@/lib/permissions";

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
const ITEM = "22222222-2222-4222-8222-222222222222";
const KEYS = [
  { key: "budget", label: "Budget" },
  { key: "timeline", label: "When they want to buy" },
  { key: "financing", label: "Financing" },
];

function item(changes: Partial<BuyerMemoryItem> = {}): BuyerMemoryItem {
  return {
    id: ITEM,
    key: "budget",
    value: "Up to 1.5 Cr",
    status: "fact",
    source: "buyer_confirmed",
    source_ref: null,
    quote: "My budget is one and a half crore.",
    reason: null,
    recorded_by_user_id: "33333333-3333-4333-8333-333333333333",
    created_at: "2026-11-12T10:00:00Z",
    ...changes,
  };
}

function memory(changes: Partial<BuyerMemory> = {}): BuyerMemory {
  return {
    keys: KEYS,
    current: [
      item(),
      item({
        id: "44444444-4444-4444-8444-444444444444",
        key: "timeline",
        value: "Within six months",
        status: "assumption",
        source: null,
        quote: null,
        reason: "Sounded in a hurry on the phone",
      }),
    ],
    history: [],
    gaps: [{ key: "financing", label: "Financing" }],
    ...changes,
  };
}

function problem(status: number, code: string) {
  return new ApiError(status, {
    title: "x",
    status,
    detail: "Server words",
    code,
    request_id: "r",
  });
}

const form = (values: [string, string][]) => {
  const data = new FormData();
  for (const [k, v] of values) data.append(k, v);
  return data;
};

// --- the words ---------------------------------------------------------------------------------

describe("helpers", () => {
  it("names the sources in words", () => {
    expect(sourceLabel("buyer_confirmed")).toBe("Buyer confirmed");
    expect(sourceLabel("website_chat")).toBe("The website chat");
    expect(sourceLabel("lead_record")).toBe("The lead form");
    expect(sourceLabel(null)).toBe("");
    expect(sourceLabel("rumour")).toBe("Another source");
  });

  it("counts the three groups", () => {
    expect(memorySummary(memory())).toBe(
      "1 fact · 1 assumption · 1 still to ask",
    );
    expect(memorySummary(memory({ current: [], gaps: KEYS }))).toBe(
      "0 facts · 0 assumptions · 3 still to ask",
    );
  });

  it("splits current entries into facts and assumptions", () => {
    const groups = groupMemory(memory());
    expect(groups.facts.map((i) => i.key)).toEqual(["budget"]);
    expect(groups.assumptions.map((i) => i.key)).toEqual(["timeline"]);
  });

  it("explains the API's refusals", () => {
    expect(memoryErrorText("memory_value_refused", "x")).toMatch(/card number/);
    expect(memoryErrorText("memory_not_current", "x")).toMatch(/newer entry/);
    expect(memoryErrorText("memory_full", "x")).toMatch(/as much/);
    expect(memoryErrorText("unknown", "Server words")).toBe("Server words");
  });

  it("shows the card only to people who may read or write it", () => {
    expect(canReadBuyerMemory({ permissions: ["buyer_memory:read"] })).toBe(
      true,
    );
    expect(canReadBuyerMemory({ permissions: ["lead:read:own"] })).toBe(false);
    expect(canWriteBuyerMemory({ permissions: ["buyer_memory:write"] })).toBe(
      true,
    );
    expect(canWriteBuyerMemory({ permissions: ["buyer_memory:read"] })).toBe(
      false,
    );
  });
});

describe("checkNewMemory", () => {
  const keys = KEYS.map((k) => k.key);
  const fact = {
    key: "budget",
    status: "fact",
    value: " 1.5 Cr ",
    quote: " said so ",
    reason: "ignored",
  };

  it("sends a fact as 'the buyer confirmed' with the quote and nothing else", () => {
    expect(checkNewMemory(fact, keys)).toEqual({
      ok: true,
      body: {
        key: "budget",
        value: "1.5 Cr",
        status: "fact",
        source: "buyer_confirmed",
        quote: "said so",
      },
    });
  });

  it("sends an assumption with its reason and no source", () => {
    expect(
      checkNewMemory(
        {
          key: "timeline",
          status: "assumption",
          value: "Soon",
          quote: "ignored",
          reason: "In a hurry",
        },
        keys,
      ),
    ).toEqual({
      ok: true,
      body: {
        key: "timeline",
        value: "Soon",
        status: "assumption",
        reason: "In a hurry",
      },
    });
  });

  it("explains what is missing", () => {
    const bad = (changes: object) => {
      const result = checkNewMemory({ ...fact, ...changes }, keys);
      return result.ok ? {} : result.fieldErrors;
    };
    expect(bad({ key: "religion" }).key).toBeTruthy();
    expect(bad({ status: "guess" }).status).toBeTruthy();
    expect(bad({ value: "  " }).value).toBeTruthy();
    expect(bad({ quote: "" }).quote).toMatch(/what the buyer said/);
    expect(bad({ status: "assumption", reason: "" }).reason).toMatch(/why/);
    expect(bad({ value: "x".repeat(301) }).value).toMatch(/too long/);
  });
});

describe("checkConfirm", () => {
  it("needs a real entry and the buyer's words; a corrected value is optional", () => {
    expect(checkConfirm({ itemId: ITEM, quote: "Yes.", value: "" })).toEqual({
      ok: true,
      body: {
        itemId: ITEM,
        body: { source: "buyer_confirmed", quote: "Yes." },
      },
    });
    expect(
      checkConfirm({ itemId: ITEM, quote: "Cash.", value: " Cash " }),
    ).toMatchObject({
      ok: true,
      body: { body: { value: "Cash" } },
    });
    expect(checkConfirm({ itemId: "../x", quote: "Yes.", value: "" }).ok).toBe(
      false,
    );
    expect(checkConfirm({ itemId: ITEM, quote: " ", value: "" }).ok).toBe(
      false,
    );
  });
});

// --- the Server Actions -----------------------------------------------------------------------

describe("server actions", () => {
  it("adds a fact: only the allowed fields go to the API, the source is forced", async () => {
    apiFetch.mockResolvedValue({});
    await expect(
      addMemory(
        LEAD,
        initialDialogState,
        form([
          ["key", "budget"],
          ["status", "fact"],
          ["value", "1.5 Cr"],
          ["quote", "Said so"],
          ["source", "lead_record"],
          ["tenant_id", "evil"],
          ["lead_id", "evil"],
          ["reason", "x"],
        ]),
      ),
    ).rejects.toThrow(`REDIRECT:/leads/${LEAD}?done=memory-added#buyer-memory`);
    const [path, init] = apiFetch.mock.calls.at(-1)!;
    expect(path).toBe(`/leads/${LEAD}/memory`);
    expect(JSON.parse(init.body)).toEqual({
      key: "budget",
      value: "1.5 Cr",
      status: "fact",
      source: "buyer_confirmed",
      quote: "Said so",
    });
  });

  it("does not call the API for a fact without a quote", async () => {
    apiFetch.mockClear();
    const state = await addMemory(
      LEAD,
      initialDialogState,
      form([
        ["key", "budget"],
        ["status", "fact"],
        ["value", "1.5 Cr"],
        ["quote", ""],
      ]),
    );
    expect(state.fieldErrors.quote).toBeTruthy();
    expect(apiFetch).not.toHaveBeenCalled();
  });

  it("refuses a tampered lead id before calling the API", async () => {
    apiFetch.mockClear();
    await expect(
      addMemory("../x", initialDialogState, form([])),
    ).rejects.toThrow("invalid lead");
    await expect(
      copyMemoryFromLead("../x", initialDialogState),
    ).rejects.toThrow("invalid lead");
    expect(apiFetch).not.toHaveBeenCalled();
  });

  it("turns a refused text into plain words", async () => {
    apiFetch.mockRejectedValue(problem(422, "memory_value_refused"));
    const state = await addMemory(
      LEAD,
      initialDialogState,
      form([
        ["key", "budget"],
        ["status", "assumption"],
        ["value", "card 4111"],
        ["reason", "why"],
      ]),
    );
    expect(state.error?.message).toMatch(/card number/);
  });

  it("confirms an assumption through the confirm call", async () => {
    apiFetch.mockResolvedValue({});
    await expect(
      confirmMemory(
        LEAD,
        initialDialogState,
        form([
          ["item_id", ITEM],
          ["quote", "Yes, a loan."],
          ["value", ""],
          ["key", "evil"],
          ["status", "fact"],
        ]),
      ),
    ).rejects.toThrow("memory-confirmed");
    const [path, init] = apiFetch.mock.calls.at(-1)!;
    expect(path).toBe(`/leads/${LEAD}/memory/${ITEM}/confirm`);
    expect(JSON.parse(init.body)).toEqual({
      source: "buyer_confirmed",
      quote: "Yes, a loan.",
    });
  });

  it("refuses an entry id that is not an id", async () => {
    apiFetch.mockClear();
    const state = await confirmMemory(
      LEAD,
      initialDialogState,
      form([
        ["item_id", "../x"],
        ["quote", "Yes."],
      ]),
    );
    expect(state.fieldErrors.item_id).toBeTruthy();
    expect(apiFetch).not.toHaveBeenCalled();
  });

  it("copies from the lead form without sending a body", async () => {
    apiFetch.mockResolvedValue({ added: 2 });
    await expect(copyMemoryFromLead(LEAD, initialDialogState)).rejects.toThrow(
      "memory-copied",
    );
    const [path, init] = apiFetch.mock.calls.at(-1)!;
    expect(path).toBe(`/leads/${LEAD}/memory/copy-from-lead`);
    expect(init.method).toBe("POST");
    expect(init.body).toBeUndefined();
  });
});

// --- the card ----------------------------------------------------------------------------------

describe("the card", () => {
  const noop = vi.fn(async (s: DialogState): Promise<DialogState> => ({
    ...s,
    attempt: s.attempt + 1,
  }));
  const noopForm = vi.fn(async (s: DialogState): Promise<DialogState> => ({
    ...s,
    attempt: s.attempt + 1,
  }));
  const view = (
    data: BuyerMemory,
    canWrite = true,
    extra: Partial<Parameters<typeof BuyerMemoryView>[0]> = {},
  ) =>
    render(
      <BuyerMemoryView
        data={data}
        canWrite={canWrite}
        addAction={noopForm}
        confirmAction={noopForm}
        copyAction={noop}
        {...extra}
      />,
    );

  it("shows facts with their source and quote, assumptions with their reason, and what is still to ask", () => {
    view(memory());
    expect(
      screen.getByText("1 fact · 1 assumption · 1 still to ask"),
    ).toBeInTheDocument();
    const facts = screen.getByRole("region", { name: "Facts" });
    expect(within(facts).getByText("Budget")).toBeInTheDocument();
    expect(within(facts).getByText("Up to 1.5 Cr")).toBeInTheDocument();
    expect(within(facts).getByText(/Buyer confirmed/)).toBeInTheDocument();
    expect(within(facts).getByText(/one and a half crore/)).toBeInTheDocument();
    const guesses = screen.getByRole("region", { name: "Assumptions" });
    expect(within(guesses).getByText("Within six months")).toBeInTheDocument();
    expect(within(guesses).getByText(/Sounded in a hurry/)).toBeInTheDocument();
    expect(within(guesses).getByText(/not confirmed/i)).toBeInTheDocument();
    const gaps = screen.getByRole("region", { name: "Still to ask" });
    expect(within(gaps).getByText("Financing")).toBeInTheDocument();
  });

  it("says so when nothing is known yet", () => {
    view(memory({ current: [], gaps: KEYS }));
    expect(screen.getByText(/Nothing recorded yet/)).toBeInTheDocument();
    expect(
      within(screen.getByRole("region", { name: "Still to ask" })).getAllByRole(
        "listitem",
      ),
    ).toHaveLength(3);
  });

  it("shows everything as plain text, never as markup or a link", () => {
    const { container } = view(
      memory({
        current: [
          item({
            value: "<img src=x onerror=alert(1)> Near metro",
            quote: "<b>bold</b> https://evil.example",
          }),
        ],
      }),
    );
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("b")).toBeNull();
    expect(screen.getByText(/<img src=x/)).toBeInTheDocument();
    expect(screen.queryByRole("link")).toBeNull();
  });

  it("shows no buttons or forms to someone who may only read", () => {
    view(memory(), false);
    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.queryByLabelText("What is it about?")).toBeNull();
  });

  it("confirms an assumption: the form asks for the buyer's words and sends the entry", async () => {
    const sentForms: FormData[] = [];
    const confirm = vi.fn(async (s: DialogState, f: FormData) => {
      sentForms.push(f);
      return s;
    });
    view(memory(), true, { confirmAction: confirm });
    const guesses = screen.getByRole("region", { name: "Assumptions" });
    await userEvent.click(
      within(guesses).getByRole("button", { name: "Confirm" }),
    );
    await userEvent.type(
      screen.getByLabelText("What did the buyer say?"),
      "Yes, within six months.",
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Confirm as fact" }),
    );
    expect(confirm).toHaveBeenCalled();
    const sent = sentForms[0];
    expect(sent.get("item_id")).toBe("44444444-4444-4444-8444-444444444444");
    expect(sent.get("quote")).toBe("Yes, within six months.");
  });

  it("adds a detail: a fact asks for the buyer's words, an assumption for the reason", async () => {
    view(memory());
    await userEvent.click(screen.getByText("Add a detail"));
    expect(screen.getByLabelText("What the buyer said")).toBeInTheDocument();
    expect(screen.queryByLabelText("Why do we think so?")).toBeNull();
    await userEvent.click(screen.getByLabelText("We think so (not confirmed)"));
    expect(screen.getByLabelText("Why do we think so?")).toBeInTheDocument();
    expect(screen.queryByLabelText("What the buyer said")).toBeNull();
  });

  it("offers all twelve keys the API gave, and the copy button", async () => {
    const copy = vi.fn(async (s: DialogState) => s);
    view(memory(), true, { copyAction: copy });
    await userEvent.click(screen.getByText("Add a detail"));
    const options = within(screen.getByLabelText("What is it about?"))
      .getAllByRole("option")
      .map((o) => o.textContent);
    expect(options).toEqual(
      expect.arrayContaining(["Budget", "When they want to buy", "Financing"]),
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Copy from the lead form" }),
    );
    expect(copy).toHaveBeenCalled();
  });

  it("keeps the history behind a fold and warns about what not to record", () => {
    view(
      memory({
        history: [
          item({
            id: "55555555-5555-4555-8555-555555555555",
            value: "Around 1.2 Cr",
            status: "assumption",
            source: null,
            quote: null,
            reason: "A guess",
          }),
        ],
      }),
    );
    expect(screen.getByText(/Earlier entries \(1\)/)).toBeInTheDocument();
    expect(screen.getByText(/Around 1\.2 Cr/)).toBeInTheDocument();
    expect(
      screen.getByText(/religion, caste, health, politics/i),
    ).toBeInTheDocument();
  });

  it("keeps what was typed when a save is refused, so nothing has to be retyped", async () => {
    const refusing = vi.fn(async (s: DialogState): Promise<DialogState> => ({
      attempt: s.attempt + 1,
      fieldErrors: { reason: "Say why we think so." },
      error: null,
    }));
    view(memory(), true, { addAction: refusing });
    await userEvent.click(screen.getByText("Add a detail"));
    await userEvent.selectOptions(
      screen.getByLabelText("What is it about?"),
      "timeline",
    );
    await userEvent.click(screen.getByLabelText("We think so (not confirmed)"));
    await userEvent.type(
      screen.getByLabelText("The detail", { exact: true }),
      "Within six months",
    );
    await userEvent.click(screen.getByRole("button", { name: "Save detail" }));
    expect(await screen.findByText("Say why we think so.")).toBeInTheDocument();
    expect(screen.getByLabelText("What is it about?")).toHaveValue("timeline");
    expect(screen.getByLabelText("We think so (not confirmed)")).toBeChecked();
    expect(screen.getByLabelText("The detail", { exact: true })).toHaveValue(
      "Within six months",
    );
  });

  it("keeps the buyer's words when a confirmation is refused", async () => {
    const refusing = vi.fn(async (s: DialogState): Promise<DialogState> => ({
      attempt: s.attempt + 1,
      fieldErrors: {},
      error: {
        status: 409,
        message: "A newer entry exists",
        code: "memory_not_current",
        requestId: "r",
        fieldErrors: {},
      },
    }));
    view(memory(), true, { confirmAction: refusing });
    const guesses = screen.getByRole("region", { name: "Assumptions" });
    await userEvent.click(
      within(guesses).getByRole("button", { name: "Confirm" }),
    );
    await userEvent.type(
      screen.getByLabelText("What did the buyer say?"),
      "Yes, within six months.",
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Confirm as fact" }),
    );
    expect(await screen.findByText(/newer entry/)).toBeInTheDocument();
    expect(screen.getByLabelText("What did the buyer say?")).toHaveValue(
      "Yes, within six months.",
    );
  });

  it("shows the API's refusal after a failed save", async () => {
    const failing = vi.fn(async (s: DialogState): Promise<DialogState> => ({
      attempt: s.attempt + 1,
      fieldErrors: { value: "Write the detail." },
      error: {
        status: 422,
        message: "That text was refused",
        code: "memory_value_refused",
        requestId: "r",
        fieldErrors: {},
      },
    }));
    view(memory(), true, { addAction: failing });
    await userEvent.click(screen.getByText("Add a detail"));
    await act(async () => {
      await userEvent.click(
        screen.getByRole("button", { name: "Save detail" }),
      );
    });
    expect(
      await screen.findByText(/That text was refused/),
    ).toBeInTheDocument();
  });
});
