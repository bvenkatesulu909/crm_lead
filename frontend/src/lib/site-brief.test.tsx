import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import PrintBriefPage from "@/app/print/leads/[id]/brief/page";
import { SiteBriefView } from "@/components/site-brief-view";
import { ApiError } from "@/lib/api-error";
import type { SiteBrief } from "@/lib/api-types";
import { askBadge, dueText, entryKind, statusText } from "@/lib/site-brief";

const apiFetch = vi.fn();
vi.mock("@/lib/server/api", () => ({
  apiFetch: (...a: unknown[]) => apiFetch(...a),
  getMe: async () => ({ permissions: ["buyer_memory:read"] }),
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

function brief(changes: Partial<SiteBrief> = {}): SiteBrief {
  return {
    as_of: "2026-11-12T14:05:00Z",
    place: null,
    buyer: {
      name: "Suresh Rao",
      status: "contacted",
      source: "web",
      owner: "Alex Agent",
      phone: "98480 12345",
      email: "suresh@example.test",
      language: "te",
      language_label: "Telugu",
    },
    facts: [
      {
        key: "budget",
        label: "Budget",
        value: "Up to 1.5 Cr",
        source: "buyer_confirmed",
        quote: "Our budget is one and a half crore.",
        recorded_on: "2026-11-10T10:00:00Z",
      },
    ],
    assumptions: [
      {
        key: "timeline",
        label: "When they want to buy",
        value: "Within six months",
        reason: "Sounded in a hurry on the phone",
        recorded_on: "2026-11-11T10:00:00Z",
      },
    ],
    ask: [
      {
        kind: "confirm",
        key: "timeline",
        label: "When they want to buy",
        text: "Confirm: When they want to buy - Within six months",
      },
      {
        kind: "gap",
        key: "financing",
        label: "Financing",
        text: "How are you planning to pay - a loan, savings, or both?",
      },
    ],
    recent: [
      {
        kind: "call",
        occurred_at: "2026-11-11T09:00:00Z",
        subject: "First call",
        excerpt: "Wants to visit on Sunday.",
      },
    ],
    tasks: [
      {
        subject: "Call back",
        due_at: "2026-11-10T09:00:00Z",
        priority: "high",
        overdue: true,
      },
      {
        subject: "Send brochure",
        due_at: null,
        priority: "normal",
        overdue: false,
      },
    ],
    cautions: [
      {
        code: "speaks_other_language",
        text: "The buyer prefers Telugu - speak (and call) in Telugu.",
      },
    ],
    ...changes,
  };
}

function problem(status: number, code: string, detail = "Server words") {
  return new ApiError(status, {
    title: "x",
    status,
    detail,
    code,
    request_id: "r",
  });
}

// --- the words ---------------------------------------------------------------------------------

describe("helpers", () => {
  it("names the badges, kinds and statuses in words", () => {
    expect(askBadge("confirm")).toBe("Confirm");
    expect(askBadge("gap")).toBe("Ask");
    expect(entryKind("email")).toBe("E-mail");
    expect(entryKind("call")).toBe("Call");
    expect(entryKind("whatever")).toBe("Note");
    expect(statusText("contacted")).toBe("Contacted");
    expect(statusText("new")).toBe("New");
  });

  it("says when a follow-up is due", () => {
    expect(
      dueText({
        subject: "x",
        due_at: null,
        priority: "normal",
        overdue: false,
      }),
    ).toBe("No due date");
    expect(
      dueText({
        subject: "x",
        due_at: "2026-11-14T09:00:00Z",
        priority: "normal",
        overdue: false,
      }),
    ).toMatch(/^Due /);
    expect(
      dueText({
        subject: "x",
        due_at: "2026-11-10T09:00:00Z",
        priority: "high",
        overdue: true,
      }),
    ).toMatch(/^Overdue since /);
  });
});

// --- the brief ---------------------------------------------------------------------------------

describe("the brief", () => {
  it("has the six sections in order", () => {
    render(<SiteBriefView brief={brief()} />);
    const headings = screen
      .getAllByRole("heading", { level: 2 })
      .map((h) => h.textContent);
    expect(headings).toEqual([
      "The buyer",
      "What we know",
      "Ask on the visit",
      "Where we left off",
      "Be careful",
    ]);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(
      "Site visit brief",
    );
  });

  it("shows the buyer, the language to call in and how to reach them", () => {
    render(<SiteBriefView brief={brief()} />);
    const buyer = screen.getByRole("region", { name: "The buyer" });
    expect(within(buyer).getByText("Suresh Rao")).toBeInTheDocument();
    expect(within(buyer).getByText("Telugu")).toBeInTheDocument();
    expect(within(buyer).getByText("98480 12345")).toBeInTheDocument();
    expect(within(buyer).getByText("suresh@example.test")).toBeInTheDocument();
    expect(within(buyer).getByText("Alex Agent")).toBeInTheDocument();
    expect(within(buyer).getByText("Contacted")).toBeInTheDocument();
  });

  it("labels every line: a fact with its source and quote, an assumption to confirm with its reason", () => {
    render(<SiteBriefView brief={brief()} />);
    const known = screen.getByRole("region", { name: "What we know" });
    const fact = within(known)
      .getByText("Up to 1.5 Cr")
      .closest("li") as HTMLElement;
    expect(within(fact).getByText("Fact")).toBeInTheDocument();
    expect(fact).toHaveTextContent("Buyer confirmed");
    expect(fact).toHaveTextContent("Our budget is one and a half crore.");
    const guess = within(known)
      .getByText("Within six months")
      .closest("li") as HTMLElement;
    expect(within(guess).getByText("Assumption")).toBeInTheDocument();
    expect(guess).toHaveTextContent("Confirm on the visit");
    expect(guess).toHaveTextContent("Sounded in a hurry on the phone");
  });

  it("lists what to ask, assumptions first, each marked", () => {
    render(<SiteBriefView brief={brief()} />);
    const ask = screen.getByRole("region", { name: "Ask on the visit" });
    const items = within(ask).getAllByRole("listitem");
    expect(items).toHaveLength(2);
    expect(items[0]).toHaveTextContent("Confirm");
    expect(items[0]).toHaveTextContent("Within six months");
    expect(items[1]).toHaveTextContent("Ask");
    expect(items[1]).toHaveTextContent("How are you planning to pay");
  });

  it("shows where we left off: the timeline and the follow-ups, overdue marked", () => {
    render(<SiteBriefView brief={brief()} />);
    const left = screen.getByRole("region", { name: "Where we left off" });
    expect(left).toHaveTextContent("First call");
    expect(left).toHaveTextContent("Wants to visit on Sunday.");
    const late = within(left)
      .getByText("Call back")
      .closest("li") as HTMLElement;
    expect(late).toHaveTextContent(/Overdue since/);
    expect(
      within(left).getByText("Send brochure").closest("li"),
    ).toHaveTextContent("No due date");
  });

  it("shows the cautions, and says so when there are none", () => {
    const { rerender } = render(<SiteBriefView brief={brief()} />);
    expect(
      screen.getByRole("region", { name: "Be careful" }),
    ).toHaveTextContent("The buyer prefers Telugu");
    rerender(<SiteBriefView brief={brief({ cautions: [] })} />);
    expect(
      screen.getByRole("region", { name: "Be careful" }),
    ).toHaveTextContent(/Nothing special/);
  });

  it("says so when there is nothing to show in a section", () => {
    render(
      <SiteBriefView
        brief={brief({
          facts: [],
          assumptions: [],
          recent: [],
          tasks: [],
          ask: [],
        })}
      />,
    );
    expect(screen.getByText(/Nothing recorded yet/)).toBeInTheDocument();
    expect(
      screen.getByText(/Nothing logged on this lead yet/),
    ).toBeInTheDocument();
    expect(screen.getByText(/No open follow-ups/)).toBeInTheDocument();
    expect(screen.getByText(/Nothing left to ask/)).toBeInTheDocument();
  });

  it("shows the place and the time the brief was put together", () => {
    render(
      <SiteBriefView brief={brief({ place: "Skyline Towers, tower B" })} />,
    );
    expect(screen.getByText(/Skyline Towers, tower B/)).toBeInTheDocument();
    expect(screen.getByText(/As of/)).toBeInTheDocument();
  });

  it("shows everything anyone wrote as plain text, never markup or a link", () => {
    const { container } = render(
      <SiteBriefView
        brief={brief({
          place: "<img src=x onerror=alert(1)> Tower",
          recent: [
            {
              kind: "note",
              occurred_at: "2026-11-11T09:00:00Z",
              subject: "<b>Bold</b>",
              excerpt: "https://evil.example <script>alert(1)</script>",
            },
          ],
        })}
      />,
    );
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("b")).toBeNull();
    expect(container.querySelector("script")).toBeNull();
    expect(screen.getByText(/<img src=x/)).toBeInTheDocument();
    expect(container.querySelector('a[href*="evil"]')).toBeNull();
  });

  it("shows a refused place in words, without losing the brief", () => {
    render(
      <SiteBriefView
        brief={brief()}
        placeError="The place was refused: that looks like a card number."
      />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("card number");
    expect(
      screen.getByRole("region", { name: "The buyer" }),
    ).toBeInTheDocument();
  });
});

// --- the page ----------------------------------------------------------------------------------

describe("the page", () => {
  const props = (id: string, place?: string) => ({
    params: Promise.resolve({ id }),
    searchParams: Promise.resolve(place === undefined ? {} : { place }),
  });
  const show = async (id: string, place?: string) =>
    render(await PrintBriefPage(props(id, place) as never));

  it("asks the API for the brief of this lead and shows it with the Print button", async () => {
    apiFetch.mockReset();
    apiFetch.mockResolvedValue(brief({ place: "Skyline Towers" }));
    await show(LEAD, "Skyline Towers");
    expect(apiFetch).toHaveBeenCalledTimes(1);
    expect(apiFetch.mock.calls[0][0]).toBe(
      `/leads/${LEAD}/brief?place=Skyline%20Towers`,
    );
    expect(
      screen.getByRole("button", { name: "Print / Save as PDF" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /Back to the lead/ }),
    ).toHaveAttribute("href", `/leads/${LEAD}`);
  });

  it("asks without a place when none was typed", async () => {
    apiFetch.mockReset();
    apiFetch.mockResolvedValue(brief());
    await show(LEAD);
    expect(apiFetch.mock.calls[0][0]).toBe(`/leads/${LEAD}/brief`);
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
    apiFetch.mockRejectedValue(problem(403, "forbidden"));
    await expect(show(LEAD)).rejects.toThrow("NOT_FOUND");
  });

  it("explains a refused place and still shows the brief", async () => {
    apiFetch.mockReset();
    apiFetch
      .mockRejectedValueOnce(
        problem(
          422,
          "brief_place_invalid",
          "The place was refused: card number",
        ),
      )
      .mockResolvedValueOnce(brief());
    await show(LEAD, "card 4111 1111 1111 1111");
    expect(apiFetch).toHaveBeenCalledTimes(2);
    expect(apiFetch.mock.calls[1][0]).toBe(`/leads/${LEAD}/brief`);
    expect(screen.getByRole("alert")).toHaveTextContent("card number");
    expect(
      screen.getByRole("region", { name: "The buyer" }),
    ).toBeInTheDocument();
  });

  it("lets the rep change the place with a plain GET form that is not printed", async () => {
    apiFetch.mockReset();
    apiFetch.mockResolvedValue(brief());
    const { container } = await show(LEAD);
    const form = container.querySelector("form") as HTMLFormElement;
    expect(form.getAttribute("method")?.toLowerCase()).toBe("get");
    expect(form.className).toMatch(/print:hidden/);
    expect(screen.getByLabelText("Where is the visit?")).toHaveAttribute(
      "maxlength",
      "100",
    );
  });
});
