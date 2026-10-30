import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { WebCheckForm } from "@/components/webcheck-form";
import { WebEvidenceList } from "@/components/webcheck-views";
import type { Me, WebCheckSource, WebEvidence } from "@/lib/api-types";
import type { DialogState } from "@/lib/dialog-state";
import { canReadWebCheck, canRunWebCheck } from "@/lib/permissions";
import {
  checkRequest,
  cleanedNotes,
  errorText,
  requestErrorText,
  statusLabel,
  verdictLabel,
} from "@/lib/webcheck";

const SOURCES: WebCheckSource[] = [
  {
    key: "demo_rera",
    title: "Demo RERA registry",
    kind: "rera",
    query_hint: "A RERA number has 5 to 40 letters, digits, '/' or '-'.",
    demo: true,
  },
  {
    key: "demo_company",
    title: "Demo company registry",
    kind: "company",
    query_hint:
      "A company name has 3 to 120 letters, digits, spaces or . , & ' ( ) -",
    demo: true,
  },
];

function evidence(changes: Partial<WebEvidence> = {}): WebEvidence {
  return {
    id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    request_id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
    source_key: "demo_rera",
    query: "DEMO/RERA/2026/001",
    requested_by_user_id: "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
    verdict: "found",
    error_code: null,
    http_status: 200,
    final_url:
      "https://registry.demo.example/rera/search?number=DEMO%2FRERA%2F2026%2F001",
    registered_name: "Lakeview Residency",
    status: "active",
    valid_until: "2028-03-31",
    excerpt:
      "Registration: DEMO/RERA/2026/001; Project: Lakeview Residency; Status: active",
    cleaned: [],
    created_at: "2026-10-30T10:00:00Z",
    ...changes,
  };
}

function me(permissions: string[]): Pick<Me, "permissions"> {
  return { permissions };
}

describe("permissions (display only; the API decides)", () => {
  it("shows the web check to people who may run or read it", () => {
    expect(canRunWebCheck(me(["webcheck:run"]))).toBe(true);
    expect(canReadWebCheck(me(["webcheck:read"]))).toBe(true);
    expect(canRunWebCheck(me(["webcheck:read"]))).toBe(false);
    expect(canReadWebCheck(me(["lead:read:all"]))).toBe(false);
    expect(canRunWebCheck(me([]))).toBe(false);
  });
});

describe("plain words", () => {
  it("names each verdict", () => {
    expect(verdictLabel("found")).toBe("Found");
    expect(verdictLabel("not_found")).toBe("Not found");
    expect(verdictLabel("unclear")).toBe("Could not be read with certainty");
    expect(verdictLabel("error")).toBe("Could not be checked");
  });

  it("names each status and never fails on a new one", () => {
    expect(statusLabel("active")).toBe("Active");
    expect(statusLabel("struck_off")).toBe("Struck off");
    expect(statusLabel("liquidation")).toBe("In liquidation");
    expect(statusLabel("something_new")).toBe("something new");
  });

  it("explains why a check could not be made", () => {
    expect(errorText("robots_disallowed")).toMatch(/robots\.txt/);
    expect(errorText("timeout")).toMatch(/did not answer in time/);
    expect(errorText("source_unavailable")).toMatch(/switched off/);
    expect(errorText("private_address")).toMatch(/not a public/i);
    expect(errorText("brand_new_code")).toBe("The check could not be made.");
    expect(errorText(null)).toBe("The check could not be made.");
  });

  it("explains why a request was refused", () => {
    expect(requestErrorText("webcheck_limit_reached")).toMatch(/many checks/);
    expect(requestErrorText("webcheck_disabled")).toMatch(/switched off/);
    expect(requestErrorText("source_unavailable")).toMatch(/not available/);
    expect(requestErrorText("record_not_found")).toMatch(/can't see/);
    expect(requestErrorText("who_knows")).toBeNull();
  });

  it("says what was cleaned, in words, without repeating the text", () => {
    expect(cleanedNotes([])).toEqual([]);
    const notes = cleanedNotes([
      "link",
      "external_image",
      "hidden_characters",
      "instruction_phrase",
    ]);
    expect(notes).toHaveLength(4);
    expect(notes.join(" ")).toMatch(/link/);
    expect(notes.join(" ")).toMatch(/image/);
    expect(notes.join(" ")).toMatch(/hidden characters/);
    expect(notes.join(" ")).toMatch(/instruction/);
    expect(cleanedNotes(["a_code_nobody_knows"])).toEqual([]);
  });
});

describe("checking the form before it is sent", () => {
  it("needs a source and a query", () => {
    expect(checkRequest({ sourceKey: "", query: "DEMO/1234" })).toEqual({
      ok: false,
      fieldErrors: { source_key: "Choose where to look." },
    });
    expect(checkRequest({ sourceKey: "demo_rera", query: "   " })).toEqual({
      ok: false,
      fieldErrors: { query: "Enter the number or name to look up." },
    });
  });

  it("trims what was typed and keeps it otherwise as it is (the API decides the shape)", () => {
    expect(
      checkRequest({ sourceKey: "demo_rera", query: "  DEMO/1234  " }),
    ).toEqual({
      ok: true,
      data: { source_key: "demo_rera", query: "DEMO/1234" },
    });
  });

  it("refuses a very long query before it leaves the browser", () => {
    const result = checkRequest({
      sourceKey: "demo_rera",
      query: "x".repeat(300),
    });
    expect(result.ok).toBe(false);
  });
});

describe("the evidence list", () => {
  const people = {} as Record<string, string>;

  it("says so when nothing was checked yet", () => {
    render(<WebEvidenceList items={[]} sources={SOURCES} />);
    expect(
      screen.getByText("No web check has been made yet."),
    ).toBeInTheDocument();
  });

  it("shows what a found registration says", () => {
    render(<WebEvidenceList items={[evidence()]} sources={SOURCES} />);
    const item = screen.getByRole("listitem");
    expect(within(item).getByText("Found")).toBeInTheDocument();
    expect(within(item).getByText("Lakeview Residency")).toBeInTheDocument();
    expect(within(item).getByText("Active")).toBeInTheDocument();
    expect(
      within(item).getByText(/Valid until 31 Mar 2028/),
    ).toBeInTheDocument();
    expect(within(item).getByText(/Demo RERA registry/)).toBeInTheDocument();
    expect(
      within(item).getAllByText(/DEMO\/RERA\/2026\/001/).length,
    ).toBeGreaterThan(0);
    expect(people).toEqual({});
  });

  it("shows a not-found answer without a name or status", () => {
    render(
      <WebEvidenceList
        items={[
          evidence({
            verdict: "not_found",
            registered_name: null,
            status: null,
            valid_until: null,
          }),
        ]}
        sources={SOURCES}
      />,
    );
    expect(screen.getByText("Not found")).toBeInTheDocument();
    expect(screen.queryByText(/Valid until/)).toBeNull();
  });

  it("explains an error in plain words", () => {
    render(
      <WebEvidenceList
        items={[
          evidence({
            verdict: "error",
            error_code: "robots_disallowed",
            http_status: null,
            registered_name: null,
            status: null,
            valid_until: null,
            excerpt: "",
          }),
        ]}
        sources={SOURCES}
      />,
    );
    expect(screen.getByText("Could not be checked")).toBeInTheDocument();
    expect(screen.getByText(/robots\.txt/)).toBeInTheDocument();
  });

  it("shows text from a page as plain text, never as markup", () => {
    const { container } = render(
      <WebEvidenceList
        items={[
          evidence({
            registered_name: "<b>Bold</b> Villas",
            excerpt: "<img src=x onerror=alert(1)>",
          }),
        ]}
        sources={SOURCES}
      />,
    );
    expect(container.querySelector("b")).toBeNull();
    expect(container.querySelector("img")).toBeNull();
    expect(screen.getByText("<b>Bold</b> Villas")).toBeInTheDocument();
  });

  it("tells the reader when text was cleaned", () => {
    render(
      <WebEvidenceList
        items={[evidence({ cleaned: ["link", "instruction_phrase"] })]}
        sources={SOURCES}
      />,
    );
    const note = screen.getByText(/Some text from the page was cleaned/);
    expect(note).toBeInTheDocument();
    expect(note.textContent).toMatch(/link/);
    expect(note.textContent).toMatch(/instruction/);
  });

  it("says nothing about cleaning when nothing was cleaned", () => {
    render(<WebEvidenceList items={[evidence()]} sources={SOURCES} />);
    expect(screen.queryByText(/cleaned/)).toBeNull();
  });

  it("falls back to the source key for a source that is no longer offered", () => {
    render(
      <WebEvidenceList
        items={[evidence({ source_key: "retired_source" })]}
        sources={SOURCES}
      />,
    );
    expect(screen.getByText(/retired_source/)).toBeInTheDocument();
  });

  it("does not link to the page that was read", () => {
    const { container } = render(
      <WebEvidenceList items={[evidence()]} sources={SOURCES} />,
    );
    expect(container.querySelector("a")).toBeNull();
  });
});

describe("the check form", () => {
  const idle = async () => ({ attempt: 0, fieldErrors: {}, error: null });

  it("asks for the right thing for the chosen source", async () => {
    const user = userEvent.setup();
    render(<WebCheckForm sources={SOURCES} action={idle} />);
    expect(screen.getByLabelText("RERA number")).toBeInTheDocument();
    expect(screen.getByText(/5 to 40 letters/)).toBeInTheDocument();
    await user.selectOptions(
      screen.getByLabelText("Where to look"),
      "demo_company",
    );
    expect(screen.getByLabelText("Company name")).toBeInTheDocument();
    expect(screen.getByText(/3 to 120 letters/)).toBeInTheDocument();
  });

  it("offers nothing when no source is switched on", () => {
    render(<WebCheckForm sources={[]} action={idle} />);
    expect(
      screen.getByText(/No web check source is switched on/),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Check" })).toBeNull();
  });

  it("sends the source and the query", async () => {
    const user = userEvent.setup();
    const action =
      vi.fn<(s: DialogState, f: FormData) => Promise<DialogState>>(idle);
    render(<WebCheckForm sources={SOURCES} action={action} />);
    await user.type(screen.getByLabelText("RERA number"), "DEMO/RERA/2026/001");
    await user.click(screen.getByRole("button", { name: "Check" }));
    await waitFor(() => expect(action).toHaveBeenCalled());
    const data = action.mock.calls[0][1] as FormData;
    expect(data.get("source_key")).toBe("demo_rera");
    expect(data.get("query")).toBe("DEMO/RERA/2026/001");
  });

  it("never sends who is asking or which organisation", async () => {
    const user = userEvent.setup();
    const action =
      vi.fn<(s: DialogState, f: FormData) => Promise<DialogState>>(idle);
    render(<WebCheckForm sources={SOURCES} action={action} />);
    await user.type(screen.getByLabelText("RERA number"), "DEMO/1234");
    await user.click(screen.getByRole("button", { name: "Check" }));
    await waitFor(() => expect(action).toHaveBeenCalled());
    const keys = [...(action.mock.calls[0][1] as FormData).keys()];
    expect(keys.sort()).toEqual(["query", "source_key"]);
  });

  it("shows the problems the server found and keeps what was typed", async () => {
    const user = userEvent.setup();
    const failing = async () => ({
      attempt: 1,
      fieldErrors: { query: "Enter the number or name to look up." },
      error: null,
    });
    render(<WebCheckForm sources={SOURCES} action={failing} />);
    await user.type(screen.getByLabelText("RERA number"), "DEMO/1");
    await user.click(screen.getByRole("button", { name: "Check" }));
    expect(
      await screen.findByText("Enter the number or name to look up."),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("RERA number")).toHaveValue("DEMO/1");
  });

  it("says in plain words when the limit was reached", async () => {
    const user = userEvent.setup();
    const limited = async () => ({
      attempt: 1,
      fieldErrors: {},
      error: {
        status: 429,
        message: "Too many web checks were asked for.",
        code: "webcheck_limit_reached",
        requestId: null,
        fieldErrors: {},
      },
    });
    render(<WebCheckForm sources={SOURCES} action={limited} />);
    await user.type(screen.getByLabelText("RERA number"), "DEMO/1234");
    await user.click(screen.getByRole("button", { name: "Check" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/many checks/);
  });
});
