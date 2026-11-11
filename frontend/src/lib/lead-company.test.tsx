import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { updateLead } from "@/app/(app)/leads/[id]/actions";
import { LeadForm } from "@/components/lead-form";
import { COMPANY_INDUSTRIES, COMPANY_SIZES } from "@/lib/api-types";
import { initialLeadFormState } from "@/lib/lead-form-state";
import { validateLead } from "@/lib/validation/lead";

/** The company behind a lead: website, industry, size band (BP-02, ADR 0026 step EN1). */

const apiFetch = vi.fn();
vi.mock("@/lib/server/api", () => ({
  apiFetch: (...a: unknown[]) => apiFetch(...a),
}));
vi.mock("next/navigation", () => ({
  usePathname: () => "/leads/new",
  redirect: (to: string) => {
    throw new Error(`REDIRECT:${to}`);
  },
}));
vi.mock("next/cache", () => ({ revalidatePath: vi.fn() }));

const LEAD = "11111111-1111-4111-8111-111111111111";

describe("lead form validation of the company fields", () => {
  const base = { last_name: "Rao" };

  it("accepts a website as people type it, a known industry and a band", () => {
    const result = validateLead({
      ...base,
      company_website: " example-builders.in ",
      company_industry: "real_estate",
      company_size: "11-50",
    });
    expect(result).toEqual({
      ok: true,
      data: {
        last_name: "Rao",
        company_website: "example-builders.in",
        company_industry: "real_estate",
        company_size: "11-50",
      },
    });
  });

  it("leaves empty company fields out", () => {
    const result = validateLead({ ...base, company_website: "", company_industry: "", company_size: "" });
    expect(result).toEqual({ ok: true, data: { last_name: "Rao" } });
  }); // prettier-ignore

  it.each([
    ["company_website", "example.com/about"],
    ["company_website", "jamie@example.com"],
    ["company_website", "example"],
    ["company_website", "exa mple.com"],
    ["company_website", "example.com:8080"],
    ["company_industry", "castles"],
    ["company_size", "1000+"],
  ])("refuses %s = %j", (field, value) => {
    const result = validateLead({ ...base, [field]: value });
    expect(result.ok).toBe(false);
    if (!result.ok)
      expect(result.errors[field as keyof typeof result.errors]).toBeTruthy();
  });

  it("offers exactly the API's industries and bands", () => {
    expect(Object.keys(COMPANY_INDUSTRIES)).toHaveLength(25);
    expect(COMPANY_SIZES).toEqual([
      "1-10",
      "11-50",
      "51-200",
      "201-1000",
      "1001+",
    ]);
  });
});

describe("LeadForm", () => {
  it("has the company group, filled in when editing", () => {
    const action = async () => initialLeadFormState;
    render(
      <LeadForm
        action={action}
        initialState={{
          ...initialLeadFormState,
          values: { last_name: "Rao", company_website: "https://example-builders.in", company_industry: "construction", company_size: "51-200" },
        }}
      />,
    );
    const company = screen.getByRole("group", { name: "About the company" });
    expect(within(company).getByRole("textbox", { name: /Website/ })).toHaveValue("https://example-builders.in");
    expect(within(company).getByRole("combobox", { name: /Industry/ })).toHaveValue("construction");
    expect(within(company).getByRole("combobox", { name: /Employees/ })).toHaveValue("51-200");
    expect(within(company).getByRole("option", { name: "Real estate" })).toBeInTheDocument();
    expect(within(company).getByRole("option", { name: "1001+ employees" })).toBeInTheDocument();
  }); // prettier-ignore
});

describe("updateLead", () => {
  function form(values: Record<string, string>) {
    const data = new FormData();
    data.set("version", "3");
    data.set("last_name", "Rao");
    for (const [k, v] of Object.entries(values)) data.set(k, v);
    return data;
  }

  it("sends the company fields, and an emptied one as null", async () => {
    apiFetch.mockResolvedValue({});
    await expect(
      updateLead(LEAD, initialLeadFormState, form({ company_website: "example.in", company_industry: "", company_size: "1-10" })),
    ).rejects.toThrow(`REDIRECT:/leads/${LEAD}`);
    const body = JSON.parse(apiFetch.mock.calls[0][1].body as string);
    expect(body).toMatchObject({
      version: 3,
      company_website: "example.in",
      company_industry: null,
      company_size: "1-10",
    });
  }); // prettier-ignore

  it("shows the API's reason for a website it refuses", async () => {
    apiFetch.mockReset();
    const result = await updateLead(LEAD, initialLeadFormState, form({ company_website: "example.com/about" }));
    expect(result.fieldErrors.company_website).toMatch(/only the website's address/);
    expect(apiFetch).not.toHaveBeenCalled();
  }); // prettier-ignore
});
