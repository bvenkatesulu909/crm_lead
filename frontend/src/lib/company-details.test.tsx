import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import {
  applyCompanyDetails,
  askCompanyDetails,
} from "@/app/(app)/webcheck/company-actions";
import {
  AskCompanyDetails,
  CompanySuggestions,
} from "@/components/company-details-views";
import { ApiError } from "@/lib/api-error";
import type { CompanyDetails, CompanySuggestion } from "@/lib/api-types";
import {
  askErrorText,
  checkApply,
  companyRows,
  lookupErrorText,
  saveErrorText,
} from "@/lib/company-details";
import { initialDialogState, type DialogState } from "@/lib/dialog-state";

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
const EVIDENCE = "22222222-2222-4222-8222-222222222222";

function suggestion(changes: Partial<CompanySuggestion> = {}) {
  return {
    id: EVIDENCE,
    created_at: "2026-11-11T10:00:00Z",
    verdict: "found",
    error_code: null,
    company_website: "https://acme.example",
    company_industry: "real_estate",
    company_size: "51-200",
    name: "Acme Homes",
    excerpt: "Name: Acme Homes",
    pages: ["https://acme.example/"],
    cleaned: [],
    ...changes,
  } as CompanySuggestion;
}

function details(
  latest: CompanySuggestion | null,
  current: Partial<CompanyDetails["current"]> = {},
): CompanyDetails {
  return {
    current: {
      company_website: null,
      company_industry: null,
      company_size: null,
      version: 3,
      ...current,
    },
    latest,
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

describe("rows", () => {
  it("offers only suggestions that differ from what the lead has", () => {
    const rows = companyRows(
      details(suggestion(), { company_website: "https://acme.example" }),
    );
    expect(rows.map((r) => [r.field, r.canApply])).toEqual([
      ["company_website", false],
      ["company_industry", true],
      ["company_size", true],
    ]);
    expect(rows[1].suggested).toBe("Real estate");
  });

  it("offers nothing for a field the website did not state", () => {
    const rows = companyRows(
      details(suggestion({ company_industry: null, company_size: null })),
    );
    expect(rows.filter((r) => r.canApply).map((r) => r.field)).toEqual([
      "company_website",
    ]);
  });
});

describe("words", () => {
  it("explains refused hosts and stored failures", () => {
    expect(askErrorText("company_host_free_mail", "x")).toMatch(/free mail/);
    expect(askErrorText("company_details_unavailable", "x")).toMatch(
      /switched off/,
    );
    expect(askErrorText("unknown_code", "Server words")).toBe("Server words");
    expect(lookupErrorText("host_internal_name")).toMatch(/not a public/);
    expect(lookupErrorText("timeout")).toMatch(/did not answer/);
    expect(saveErrorText("version_conflict", "x")).toMatch(/Reload/);
  });
});

describe("checkApply", () => {
  const ok = { fields: ["company_size"], version: "3", evidenceId: EVIDENCE };
  it("accepts named fields", () => {
    expect(checkApply(ok)).toMatchObject({ ok: true, version: 3 });
  });
  it("refuses nothing ticked, unknown or repeated fields, bad version or id", () => {
    expect(checkApply({ ...ok, fields: [] }).ok).toBe(false);
    expect(checkApply({ ...ok, fields: ["owner_id"] }).ok).toBe(false);
    expect(
      checkApply({ ...ok, fields: ["company_size", "company_size"] }).ok,
    ).toBe(false);
    expect(checkApply({ ...ok, version: "0" }).ok).toBe(false);
    expect(checkApply({ ...ok, evidenceId: "../x" }).ok).toBe(false);
  });
});

describe("server actions", () => {
  function form(values: [string, string][]) {
    const data = new FormData();
    for (const [k, v] of values) data.append(k, v);
    return data;
  }

  it("asks with only the lead", async () => {
    apiFetch.mockResolvedValue({});
    await expect(askCompanyDetails(LEAD, initialDialogState)).rejects.toThrow(
      `REDIRECT:/leads/${LEAD}?done=company-queued#company-details`,
    );
    expect(JSON.parse(apiFetch.mock.calls[0][1].body)).toEqual({
      lead_id: LEAD,
    });
  });

  it("refuses a tampered lead id before calling the API", async () => {
    apiFetch.mockClear();
    await expect(askCompanyDetails("../x", initialDialogState)).rejects.toThrow(
      "invalid lead",
    );
    expect(apiFetch).not.toHaveBeenCalled();
  });

  it("turns a refused ask into plain words", async () => {
    apiFetch.mockRejectedValue(problem(422, "company_host_free_mail"));
    const state = await askCompanyDetails(LEAD, initialDialogState);
    expect(state.error?.message).toMatch(/free mail/);
  });

  it("saves only names of fields, never values", async () => {
    apiFetch.mockClear();
    apiFetch.mockResolvedValue({});
    await expect(
      applyCompanyDetails(
        LEAD,
        initialDialogState,
        form([
          ["field", "company_size"],
          ["version", "3"],
          ["evidence_id", EVIDENCE],
          ["company_size", "1001+"],
          ["value", "evil"],
        ]),
      ),
    ).rejects.toThrow("company-saved");
    expect(JSON.parse(apiFetch.mock.calls[0][1].body)).toEqual({
      lead_id: LEAD,
      evidence_id: EVIDENCE,
      fields: ["company_size"],
      version: 3,
    });
  });

  it("does not call the API when nothing is ticked", async () => {
    apiFetch.mockClear();
    const state = await applyCompanyDetails(
      LEAD,
      initialDialogState,
      form([
        ["version", "3"],
        ["evidence_id", EVIDENCE],
      ]),
    );
    expect(state.fieldErrors.field).toMatch(/Tick at least one/);
    expect(apiFetch).not.toHaveBeenCalled();
  });

  it("explains a version conflict", async () => {
    apiFetch.mockRejectedValue(problem(409, "version_conflict"));
    const state = await applyCompanyDetails(
      LEAD,
      initialDialogState,
      form([
        ["field", "company_size"],
        ["version", "3"],
        ["evidence_id", EVIDENCE],
      ]),
    );
    expect(state.error?.message).toMatch(/Someone changed/);
  });
});

describe("the card", () => {
  const noop = vi.fn(async (s: DialogState): Promise<DialogState> => ({
    ...s,
    attempt: s.attempt + 1,
  }));

  it("says so when nothing was looked up yet", () => {
    render(
      <CompanySuggestions details={details(null)} action={noop} canSave />,
    );
    expect(screen.getByText(/No look-up yet/)).toBeInTheDocument();
  });

  it("shows suggestions beside the current values with ticked rows", () => {
    render(
      <CompanySuggestions
        details={details(suggestion(), { company_size: "1-10" })}
        action={noop}
        canSave
      />,
    );
    expect(screen.getByText("Real estate")).toBeInTheDocument();
    expect(screen.getByText("1-10")).toBeInTheDocument();
    expect(screen.getByLabelText("Save Industry")).toBeChecked();
    expect(
      screen.getByRole("button", { name: "Save the ticked details" }),
    ).toBeInTheDocument();
  });

  it("shows a page's words as plain text, never as markup or a link", () => {
    render(
      <CompanySuggestions
        details={details(
          suggestion({ excerpt: "<img src=x onerror=alert(1)> Hello" }),
        )}
        action={noop}
        canSave
      />,
    );
    expect(screen.getByText(/<img src=x/)).toBeInTheDocument();
    expect(screen.queryByRole("link")).toBeNull();
  });

  it("shows no checkboxes or save button to someone who may only read", () => {
    render(
      <CompanySuggestions
        details={details(suggestion())}
        action={noop}
        canSave={false}
      />,
    );
    expect(screen.queryByRole("checkbox")).toBeNull();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("explains a lookup that failed and offers no save", () => {
    render(
      <CompanySuggestions
        details={details(
          suggestion({
            verdict: "error",
            error_code: "host_free_mail",
            company_website: null,
            company_industry: null,
            company_size: null,
          }),
        )}
        action={noop}
        canSave
      />,
    );
    expect(screen.getByText(/free mail service/)).toBeInTheDocument();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("tells the reader when text was cleaned", () => {
    render(
      <CompanySuggestions
        details={details(suggestion({ cleaned: ["link"] }))}
        action={noop}
        canSave
      />,
    );
    expect(screen.getByText(/a link was removed/)).toBeInTheDocument();
  });

  it("asks for a look-up when the button is pressed", async () => {
    const ask = vi.fn(async (s: DialogState) => s);
    render(<AskCompanyDetails action={ask} />);
    await userEvent.click(
      screen.getByRole("button", { name: "Find company details" }),
    );
    expect(ask).toHaveBeenCalled();
  });
});
