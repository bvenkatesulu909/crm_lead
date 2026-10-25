import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { LeadForm } from "@/components/lead-form";
import { formatBudget, formatRupees, parseRupees } from "@/lib/format";
import { initialLeadFormState } from "@/lib/lead-form-state";
import { validateLead } from "@/lib/validation/lead";

vi.mock("next/navigation", () => ({ usePathname: () => "/leads/new" }));

/** Real-estate fields on leads (ADR 0013, step PC2): budgets in whole rupees. */
describe("parseRupees", () => {
  it.each([
    ["12000000", 12_000_000],
    ["1,20,00,000", 12_000_000], // Indian grouping
    ["1.2 Cr", 12_000_000],
    ["1.25 crore", 12_500_000],
    ["2 Cr", 20_000_000],
    ["80 L", 8_000_000],
    ["80 lakh", 8_000_000],
    ["7.5 lac", 750_000],
    ["₹ 95,000", 95_000],
    ["Rs. 1.5cr", 15_000_000],
    ["0", 0],
  ])("%j is %d rupees", (text, rupees) => {
    expect(parseRupees(text)).toBe(rupees);
  });

  // "12.345 L" would be valid (₹12,34,500); six decimals of a lakh are a fraction of a rupee.
  it.each(["", "abc", "1.5", "12.345678 L", "1.23456789 Cr", "-5", "5 million", "1 Cr 2 L", "1e7"])(
    "%j is not a whole-rupee budget",
    (text) => {
      expect(parseRupees(text)).toBeNull();
    },
  );

  it("never uses floating point: 1.1 Cr is exactly 11000000", () => {
    expect(parseRupees("1.1 Cr")).toBe(11_000_000);
    expect(parseRupees("0.07 Cr")).toBe(700_000);
  });
});

describe("formatting budgets", () => {
  it("shows crore and lakh the Indian way", () => {
    expect(formatRupees(12_000_000)).toBe("₹1.2 Cr");
    expect(formatRupees(20_000_000)).toBe("₹2 Cr");
    expect(formatRupees(8_000_000)).toBe("₹80 L");
    expect(formatRupees(95_000)).toBe("₹95,000");
  });

  it("shows a range, one side, or nothing", () => {
    expect(formatBudget(12_000_000, 15_000_000)).toBe("₹1.2 Cr – ₹1.5 Cr");
    expect(formatBudget(8_000_000, null)).toBe("from ₹80 L");
    expect(formatBudget(null, 20_000_000)).toBe("up to ₹2 Cr");
    expect(formatBudget(5_000_000, 5_000_000)).toBe("₹50 L");
    expect(formatBudget(null, undefined)).toBe("—");
  });
});

describe("lead form validation (mirrors the backend)", () => {
  const base = { last_name: "Rao" };

  it("turns the typed budget into whole rupees", () => {
    const result = validateLead({
      ...base,
      property_type: "apartment",
      budget_min_inr: "1.2 Cr",
      budget_max_inr: "1,50,00,000",
      location: " Kokapet ",
    });
    expect(result).toEqual({
      ok: true,
      data: {
        last_name: "Rao",
        property_type: "apartment",
        budget_min_inr: 12_000_000,
        budget_max_inr: 15_000_000,
        location: "Kokapet",
      },
    });
  });

  it("leaves empty fields out", () => {
    expect(validateLead({ ...base, property_type: "", budget_min_inr: "", location: "" })).toEqual({
      ok: true,
      data: { last_name: "Rao" },
    });
  });

  it.each([
    [{ property_type: "castle" }, "property_type"],
    [{ budget_min_inr: "a lot" }, "budget_min_inr"],
    [{ budget_max_inr: "1.5" }, "budget_max_inr"],
    [{ budget_max_inr: "200000 Cr" }, "budget_max_inr"], // above the 1 lakh crore typo guard
    [{ location: "x".repeat(161) }, "location"],
    [{ budget_min_inr: "2 Cr", budget_max_inr: "1 Cr" }, "budget_max_inr"],
  ] as const)("refuses %j", (values, field) => {
    const result = validateLead({ ...base, ...values });
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.errors[field]).toBeTruthy();
  });
});

describe("LeadForm", () => {
  it("has the property wishes, filled in when editing", () => {
    const action = async () => initialLeadFormState;
    render(
      <LeadForm
        action={action}
        initialState={{
          ...initialLeadFormState,
          values: { last_name: "Rao", property_type: "villa", budget_max_inr: "30000000", location: "Gachibowli" },
        }}
      />,
    );
    const wishes = screen.getByRole("group", { name: "Property wishes" });
    expect(within(wishes).getByRole("combobox", { name: /Property type/ })).toHaveValue("villa");
    expect(within(wishes).getByRole("textbox", { name: /Maximum budget/ })).toHaveValue("30000000");
    expect(within(wishes).getByRole("textbox", { name: /Minimum budget/ })).toHaveValue("");
    expect(within(wishes).getByRole("textbox", { name: /Location/ })).toHaveValue("Gachibowli");
  }); // prettier-ignore
});
