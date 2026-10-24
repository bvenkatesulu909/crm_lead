import { describe, expect, it } from "vitest";

import { CONTRACT_STATUSES } from "@/lib/api-types";
import {
  BILLING_LABELS,
  CONTRACT_STATUS_LABELS,
  CONTRACT_STATUS_STYLE,
  eventTitle,
  endHint,
} from "@/lib/contracts";
import {
  canManageContracts,
  canReadContracts,
  canWriteContracts,
  navigationFor,
} from "@/lib/permissions";
import {
  activeContractSchema,
  contractErrors,
  contractSchema,
  draftContractSchema,
} from "@/lib/validation/contracts";

const ACCOUNT = "11111111-1111-4111-8111-111111111111";
const valid = {
  account_id: ACCOUNT,
  title: "Support agreement",
  start_date: "2027-01-01",
  end_date: "2027-12-31",
  total_value: "12000.50",
  currency: "eur",
  billing_frequency: "annually",
  auto_renew: "on",
  renewal_notice_days: "30",
  renewal_term_months: "12",
  terms: "Net 30",
};

describe("contract labels", () => {
  it("has a label and a style for every status", () => {
    for (const status of CONTRACT_STATUSES) {
      expect(CONTRACT_STATUS_LABELS[status]).toBeTruthy();
      expect(CONTRACT_STATUS_STYLE[status]).toBeTruthy();
    }
    expect(Object.keys(BILLING_LABELS)).toEqual([
      "one_time",
      "monthly",
      "quarterly",
      "annually",
    ]);
  });

  it("titles history entries in plain words", () => {
    const base = { note: null, created_at: "", actor_name: null };
    expect(
      eventTitle({
        ...base,
        event_type: "status_changed",
        from_status: "draft",
        to_status: "active",
      }),
    ).toBe("Status: Active");
    expect(
      eventTitle({
        ...base,
        event_type: "created",
        from_status: null,
        to_status: "draft",
      }),
    ).toBe("Created as a draft");
    expect(
      eventTitle({
        ...base,
        event_type: "renewal_reminder",
        from_status: null,
        to_status: null,
      }),
    ).toBe("Renewal reminder");
  });
});

describe("endHint", () => {
  it("says nothing unless the contract is running", () => {
    for (const status of ["draft", "expired", "terminated", "renewed"] as const)
      expect(endHint({ status, days_to_end: 5 })).toEqual({
        text: "",
        tone: "none",
      });
    expect(endHint({ status: "active", days_to_end: null }).tone).toBe("none");
  });

  it("counts down, with the right wording and tone", () => {
    expect(endHint({ status: "active", days_to_end: 90 })).toEqual({
      text: "Ends in 90 days",
      tone: "ok",
    });
    expect(endHint({ status: "active", days_to_end: 31 }).tone).toBe("ok");
    expect(endHint({ status: "active", days_to_end: 30 })).toEqual({
      text: "Ends in 30 days",
      tone: "soon",
    });
    expect(endHint({ status: "active", days_to_end: 1 })).toEqual({
      text: "Ends in 1 day",
      tone: "soon",
    });
    expect(endHint({ status: "active", days_to_end: 0 })).toEqual({
      text: "Ends today",
      tone: "soon",
    });
    expect(endHint({ status: "active", days_to_end: -1 })).toEqual({
      text: "Ended 1 day ago",
      tone: "late",
    });
    expect(endHint({ status: "active", days_to_end: -12 })).toEqual({
      text: "Ended 12 days ago",
      tone: "late",
    });
  });
});

describe("contract form validation (same limits as the API)", () => {
  it("accepts a good contract and cleans the values", () => {
    const parsed = contractSchema.safeParse(valid);
    expect(parsed.success).toBe(true);
    if (parsed.success)
      expect(parsed.data).toMatchObject({
        currency: "EUR", // upper-cased
        total_value: "12000.50",
        auto_renew: true,
        renewal_notice_days: 30,
        renewal_term_months: 12,
      });
  });

  it("treats empty optional fields as 'not set'", () => {
    const parsed = contractSchema.safeParse({
      ...valid,
      start_date: "",
      end_date: "",
      renewal_term_months: "",
      terms: "  ",
      auto_renew: "",
    });
    expect(parsed.success).toBe(true);
    if (parsed.success)
      expect(parsed.data).toMatchObject({
        start_date: null,
        end_date: null,
        renewal_term_months: null,
        terms: null,
        auto_renew: false,
      });
  });

  it("accepts a decimal comma in the value", () => {
    const parsed = contractSchema.safeParse({
      ...valid,
      total_value: "1500,25",
    });
    expect(parsed.success && parsed.data.total_value).toBe("1500.25");
  });

  const bad: [string, Partial<typeof valid>, string, string][] = [
    [
      "no account",
      { account_id: "" },
      "account_id",
      "Choose the customer account.",
    ],
    [
      "a made-up account id",
      { account_id: "not-an-id" },
      "account_id",
      "Choose the customer account.",
    ],
    ["an empty title", { title: "   " }, "title", "Give the contract a title."],
    [
      "a very long title",
      { title: "x".repeat(201) },
      "title",
      "Title can be at most 200 characters.",
    ],
    [
      "dates in the wrong order",
      { start_date: "2027-06-01", end_date: "2027-01-01" },
      "end_date",
      "The end date cannot be before the start date.",
    ],
    [
      "a malformed date",
      { start_date: "01/02/2027" },
      "start_date",
      "Enter the start date.",
    ],
    [
      "a negative value",
      { total_value: "-5" },
      "total_value",
      "Enter an amount such as 12000.50 (up to 2 decimals).",
    ],
    [
      "three decimals",
      { total_value: "10.123" },
      "total_value",
      "Enter an amount such as 12000.50 (up to 2 decimals).",
    ],
    [
      "text as value",
      { total_value: "a lot" },
      "total_value",
      "Enter an amount such as 12000.50 (up to 2 decimals).",
    ],
    [
      "a long currency",
      { currency: "EURO" },
      "currency",
      "Use a 3-letter currency code, e.g. EUR.",
    ],
    [
      "an unknown billing",
      { billing_frequency: "daily" },
      "billing_frequency",
      "Choose how often it is billed.",
    ],
    [
      "notice over a year",
      { renewal_notice_days: "400" },
      "renewal_notice_days",
      "Notice can be 0 to 365 days.",
    ],
    [
      "a blank notice",
      { renewal_notice_days: "" },
      "renewal_notice_days",
      "Notice can be 0 to 365 days.",
    ],
    [
      "a zero-month term",
      { renewal_term_months: "0" },
      "renewal_term_months",
      "The renewal term can be 1 to 120 months.",
    ],
    [
      "a 121-month term",
      { renewal_term_months: "121" },
      "renewal_term_months",
      "The renewal term can be 1 to 120 months.",
    ],
    [
      "too many terms",
      { terms: "x".repeat(10001) },
      "terms",
      "The terms can be at most 10,000 characters.",
    ],
  ];
  it.each(bad)("refuses %s", (_name, change, field, message) => {
    const parsed = contractSchema.safeParse({ ...valid, ...change });
    expect(parsed.success).toBe(false);
    if (!parsed.success)
      expect(contractErrors(parsed.error)[field]).toBe(message);
  });

  it("an active contract may only change its renewal settings, title and terms", () => {
    const parsed = activeContractSchema.safeParse(valid);
    expect(parsed.success).toBe(true);
    if (parsed.success)
      // Dates, value, currency and billing are not even part of what is sent.
      expect(Object.keys(parsed.data).sort()).toEqual([
        "auto_renew",
        "renewal_notice_days",
        "renewal_term_months",
        "terms",
        "title",
      ]);
  });

  it("a draft edit leaves out the account (it never changes)", () => {
    const parsed = draftContractSchema.safeParse(valid);
    expect(parsed.success && "account_id" in parsed.data).toBe(false);
  });
});

describe("who sees contracts", () => {
  const as = (...permissions: string[]) => ({
    permissions,
    user_type: "staff" as const,
  });

  it("reads, writes and manages are separate permissions", () => {
    expect(canReadContracts(as("contract:read:own"))).toBe(true);
    expect(canReadContracts(as("quote:read:all"))).toBe(false);
    expect(canWriteContracts(as("contract:write:own"))).toBe(true);
    expect(canWriteContracts(as("contract:read:all"))).toBe(false);
    expect(canManageContracts(as("contract:manage"))).toBe(true);
    expect(canManageContracts(as("contract:write:all"))).toBe(false);
  });

  it("shows the menu entry only to people who may read contracts", () => {
    const labels = (permissions: string[]) =>
      navigationFor(as(...permissions)).map((i) => i.label);
    expect(labels(["contract:read:own"])).toContain("Contracts");
    expect(labels(["contract:read:all", "quote:read:all"])).toEqual([
      "Dashboard",
      "Quotes",
      "Contracts",
      "Reports", // anyone who may read quotes also gets the reports
    ]);
    expect(labels(["ticket:read:all"])).not.toContain("Contracts");
    expect(
      navigationFor({
        permissions: ["contract:read:all"],
        user_type: "customer",
      }),
    ).toEqual([]);
  });
});
