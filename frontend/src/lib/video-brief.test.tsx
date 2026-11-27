import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import VideoBriefPage from "@/app/print/leads/[id]/video-brief/page";
import { VideoBriefView } from "@/components/video-brief-view";
import { ApiError } from "@/lib/api-error";
import type { VideoBrief } from "@/lib/api-types";
import { canReadVideoBrief } from "@/lib/permissions";
import {
  briefPath,
  knownBadge,
  parseChoices,
  quoteOptionLabel,
  quoteProblemText,
  quotesPath,
  scriptBadge,
} from "@/lib/video-brief";

const apiFetch = vi.fn();
vi.mock("@/lib/server/api", () => ({
  apiFetch: (...a: unknown[]) => apiFetch(...a),
  getMe: async () => ({ permissions: ["video_brief:read"] }),
}));
vi.mock("next/navigation", () => ({
  notFound: () => {
    throw new Error("NOT_FOUND");
  },
}));
vi.mock("@/components/print-button", () => ({
  PrintButton: () => <button type="button">Print / Save as PDF</button>,
}));

const LEAD = "11111111-1111-4111-8111-111111111111";
const QUOTE = "22222222-2222-4222-8222-222222222222";
const ACCOUNT = "33333333-3333-4333-8333-333333333333";

function brief(changes: Partial<VideoBrief> = {}): VideoBrief {
  return {
    first_name: "Suresh",
    language: "te",
    tone: "warm",
    tone_note: "Speak warmly and slowly.",
    goal: "follow_up",
    length_seconds: 60,
    word_target: 150,
    words: 40,
    known: [
      {
        kind: "fact",
        key: "budget",
        label: "Budget",
        value: "Up to 1.5 Cr",
        source: "buyer_confirmed",
        quote: "Our budget is one and a half crore.",
        reason: null,
      },
      {
        kind: "assumption",
        key: "timeline",
        label: "Timeline",
        value: "Within six months",
        source: null,
        quote: null,
        reason: "Sounded in a hurry",
      },
      {
        kind: "form",
        key: "location",
        label: "Area",
        value: "Kokapet",
        source: "lead_form",
        quote: null,
        reason: null,
      },
      {
        kind: "price",
        key: "total",
        label: "Total",
        value: "₹1,20,00,000",
        source: "QT-0007",
        quote: null,
        reason: null,
      },
    ],
    script: [
      { kind: "greeting", text: "Hello Suresh,", cites: [], seconds: 1 },
      {
        kind: "fact",
        text: "On Budget you said: Up to 1.5 Cr.",
        cites: ["budget"],
        seconds: 3,
      },
      {
        kind: "question",
        text: "Is Within six months still right?",
        cites: ["timeline"],
        seconds: 3,
      },
      { kind: "closing", text: "Thank you.", cites: [], seconds: 1 },
    ],
    must_say: ["Say the RERA number."],
    must_not_say: ["Never promise guaranteed returns."],
    consent_notes: ["Check the buyer's consent first."],
    cautions: [],
    ...changes,
  };
}

function problem(status: number, code: string) {
  return new ApiError(status, { code, detail: code } as never);
}

describe("the helpers", () => {
  it("falls back to the defaults for anything outside the fixed lists", () => {
    expect(
      parseChoices({
        goal: "spam",
        language: "fr",
        tone: "angry",
        length: "45",
        quote_id: "not-an-id",
      }),
    ).toEqual({
      goal: "follow_up",
      language: "",
      tone: "warm",
      length: 60,
      quoteId: "",
    });
  });

  it("keeps valid choices", () => {
    expect(
      parseChoices({
        goal: "after_visit",
        language: "hi",
        tone: "brisk",
        length: "30",
        quote_id: QUOTE,
      }),
    ).toEqual({
      goal: "after_visit",
      language: "hi",
      tone: "brisk",
      length: 30,
      quoteId: QUOTE,
    });
  });

  it("builds the API path without a language or quote when none was chosen", () => {
    const base = parseChoices({});
    expect(briefPath(LEAD, base)).toBe(
      `/leads/${LEAD}/video-brief?goal=follow_up&tone=warm&length=60`,
    );
    expect(briefPath(LEAD, { ...base, language: "hi", quoteId: QUOTE })).toBe(
      `/leads/${LEAD}/video-brief?goal=follow_up&tone=warm&length=60&language=hi&quote_id=${QUOTE}`,
    );
  });

  it("lists only quotes whose prices may be spoken", () => {
    expect(quotesPath(ACCOUNT)).toBe(
      `/quotes?account_id=${ACCOUNT}&status=approved&status=sent&status=accepted&limit=50`,
    );
  });

  it("labels a quote like the quote pages do", () => {
    expect(
      quoteOptionLabel({
        number: 7,
        revision: 2,
        title: "Tower B",
        status: "sent",
      }),
    ).toBe("QT-0007 rev 2: Tower B (sent)");
    expect(
      quoteOptionLabel({
        number: 7,
        revision: 1,
        title: "Tower B",
        status: "sent",
      }),
    ).toBe("QT-0007: Tower B (sent)");
  });

  it("has words for every kind of line and every refused quote", () => {
    expect(knownBadge("form")).toBe("Lead form");
    expect(scriptBadge("question")).toBe("Question");
    expect(quoteProblemText("quote_not_found")).toMatch(
      /not one of this buyer/,
    );
    expect(quoteProblemText("video_brief_quote_not_ready")).toMatch(
      /approved, sent or accepted/,
    );
    expect(quoteProblemText("other")).toBeNull();
  });

  it("shows the button only to people who may read video briefs", () => {
    expect(canReadVideoBrief({ permissions: ["video_brief:read"] })).toBe(true);
    expect(canReadVideoBrief({ permissions: ["buyer_memory:read"] })).toBe(
      false,
    );
  });
});

describe("VideoBriefView", () => {
  it("shows the script in order with each line marked and its source", () => {
    render(<VideoBriefView brief={brief()} />);
    const script = screen.getByRole("region", { name: "The script" });
    const lines = within(script).getAllByRole("listitem");
    expect(lines).toHaveLength(4);
    expect(lines[1]).toHaveTextContent("Fact");
    expect(lines[1]).toHaveTextContent("from budget");
    expect(lines[2]).toHaveTextContent("Question");
    expect(lines[0].querySelector("[lang='te']")).not.toBeNull();
  });

  it("says what each source line is allowed to do", () => {
    render(<VideoBriefView brief={brief()} />);
    const built = screen.getByRole("region", { name: "What it is built from" });
    expect(built).toHaveTextContent("Our budget is one and a half crore.");
    expect(built).toHaveTextContent("Only asked as a question");
    expect(built).toHaveTextContent(
      "Shown only: the buyer has not confirmed it",
    );
    expect(built).toHaveTextContent("Source: QT-0007");
  });

  it("shows the must say, never say and consent lists", () => {
    render(<VideoBriefView brief={brief()} />);
    expect(screen.getByRole("region", { name: "Say this" })).toHaveTextContent(
      "RERA",
    );
    expect(
      screen.getByRole("region", { name: "Never say this" }),
    ).toHaveTextContent("guaranteed");
    expect(
      screen.getByRole("region", { name: "Consent and privacy" }),
    ).toHaveTextContent("consent");
  });

  it("marks a script that is too long and notes the native-speaker read for Hindi and Telugu", () => {
    render(<VideoBriefView brief={brief({ words: 200 })} />);
    expect(
      screen.getByText(/200 words; 60 seconds holds about 150/),
    ).toHaveClass("text-red-700");
    expect(screen.getByText(/native speaker/)).toBeInTheDocument();
  });

  it("does not claim a native-speaker read for English", () => {
    render(<VideoBriefView brief={brief({ language: "en" })} />);
    expect(screen.queryByText(/native speaker/)).toBeNull();
  });

  it("shows every text as plain text, never as markup or a link", () => {
    const hostile =
      '<img src=x onerror="alert(1)"> <a href="https://evil.example">x</a>';
    const { container } = render(
      <VideoBriefView
        brief={brief({
          first_name: hostile,
          script: [
            { kind: "fact", text: hostile, cites: [hostile], seconds: 1 },
          ],
          cautions: [{ code: "x", text: hostile }],
        })}
      />,
    );
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("a")).toBeNull();
    expect(container.textContent).toContain("<img src=x");
  });

  it("shows notices as alerts and an empty state when nothing is known", () => {
    render(
      <VideoBriefView
        brief={brief({ known: [] })}
        notices={["No prices were added."]}
      />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent(
      "No prices were added.",
    );
    expect(screen.getByText(/Nothing recorded yet/)).toBeInTheDocument();
  });
});

describe("the page", () => {
  const props = (id: string, sp: Record<string, string> = {}) => ({
    params: Promise.resolve({ id }),
    searchParams: Promise.resolve(sp),
  });
  const show = async (id: string, sp: Record<string, string> = {}) =>
    render(await VideoBriefPage(props(id, sp) as never));
  const lead = (account: string | null) => ({ converted_account_id: account });

  it("asks for the lead, then the brief with the chosen values", async () => {
    apiFetch.mockReset();
    apiFetch.mockResolvedValueOnce(lead(null)).mockResolvedValueOnce(brief());
    await show(LEAD, { goal: "revive", length: "90" });
    expect(apiFetch.mock.calls[0][0]).toBe(`/leads/${LEAD}`);
    expect(apiFetch.mock.calls[1][0]).toBe(
      `/leads/${LEAD}/video-brief?goal=revive&tone=warm&length=90`,
    );
    expect(
      screen.getByRole("button", { name: "Print / Save as PDF" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /Back to the lead/ }),
    ).toHaveAttribute("href", `/leads/${LEAD}`);
    expect(screen.queryByLabelText("Quote to take the prices from")).toBeNull();
  });

  it("offers the usable quotes of the account the lead became", async () => {
    apiFetch.mockReset();
    apiFetch
      .mockResolvedValueOnce(lead(ACCOUNT))
      .mockResolvedValueOnce({
        items: [
          {
            id: QUOTE,
            number: 7,
            revision: 1,
            title: "Tower B",
            status: "sent",
          },
        ],
      })
      .mockResolvedValueOnce(brief());
    await show(LEAD);
    expect(apiFetch.mock.calls[1][0]).toBe(quotesPath(ACCOUNT));
    const select = screen.getByLabelText("Quote to take the prices from");
    expect(
      within(select)
        .getAllByRole("option")
        .map((o) => o.textContent),
    ).toEqual(["No prices", "QT-0007: Tower B (sent)"]);
  });

  it("still shows the brief when the quote list cannot be loaded", async () => {
    apiFetch.mockReset();
    apiFetch
      .mockResolvedValueOnce(lead(ACCOUNT))
      .mockRejectedValueOnce(problem(500, "boom"))
      .mockResolvedValueOnce(brief());
    await show(LEAD);
    expect(
      screen.getByRole("region", { name: "The script" }),
    ).toBeInTheDocument();
  });

  it("refuses an id that is not an id before calling the API", async () => {
    apiFetch.mockReset();
    await expect(show("../x")).rejects.toThrow("NOT_FOUND");
    expect(apiFetch).not.toHaveBeenCalled();
  });

  it("shows 'not found' for a lead the person may not read", async () => {
    apiFetch.mockReset();
    apiFetch.mockRejectedValue(problem(404, "lead_not_found"));
    await expect(show(LEAD)).rejects.toThrow("NOT_FOUND");
    apiFetch.mockReset();
    apiFetch.mockRejectedValue(problem(403, "forbidden"));
    await expect(show(LEAD)).rejects.toThrow("NOT_FOUND");
  });

  it("explains a refused quote and still shows the brief without prices", async () => {
    apiFetch.mockReset();
    apiFetch
      .mockResolvedValueOnce(lead(null))
      .mockRejectedValueOnce(problem(422, "video_brief_quote_not_ready"))
      .mockResolvedValueOnce(brief());
    await show(LEAD, { quote_id: QUOTE });
    expect(apiFetch.mock.calls[1][0]).toContain(`quote_id=${QUOTE}`);
    expect(apiFetch.mock.calls[2][0]).not.toContain("quote_id");
    expect(screen.getByRole("alert")).toHaveTextContent(
      /approved, sent or accepted/,
    );
  });

  it("explains a quote that is not this buyer's", async () => {
    apiFetch.mockReset();
    apiFetch
      .mockResolvedValueOnce(lead(null))
      .mockRejectedValueOnce(problem(404, "quote_not_found"))
      .mockResolvedValueOnce(brief());
    await show(LEAD, { quote_id: QUOTE });
    expect(screen.getByRole("alert")).toHaveTextContent(
      /not one of this buyer/,
    );
  });

  it("treats a 404 for the brief itself as not found", async () => {
    apiFetch.mockReset();
    apiFetch
      .mockResolvedValueOnce(lead(null))
      .mockRejectedValueOnce(problem(404, "lead_not_found"));
    await expect(show(LEAD)).rejects.toThrow("NOT_FOUND");
  });
});
