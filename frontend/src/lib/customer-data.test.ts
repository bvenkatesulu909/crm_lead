import { describe, expect, it } from "vitest";

import {
  contactApiQuery,
  contactPageHref,
  parseContactParams,
} from "@/app/(app)/contacts/list-params";
import type { TimelineEntry } from "@/lib/api-types";
import { describeChanges, relationshipTimeline } from "@/lib/customer-data";
import {
  accountSchema,
  contactSchema,
  readForm,
  withCheckboxes,
  withoutNulls,
} from "@/lib/validation/customer-data";

const ACCOUNT = "ac000000-0000-4000-8000-0000000000a1";

const account = (over: Record<string, string> = {}) => ({
  name: "Example Co",
  account_number: "",
  website: "",
  industry: "",
  phone: "",
  segment: "",
  preferred_channel: "",
  parent_account_id: "",
  country: "",
  region: "",
  city: "",
  lifecycle_stage: "",
  account_type: "company",
  preferred_language: "",
  ...over,
});

const contact = (over: Record<string, string> = {}) => ({
  first_name: "",
  last_name: "Example",
  email: "",
  phone: "",
  mobile: "",
  job_title: "",
  department: "",
  account_id: "",
  is_primary: "",
  preferred_channel: "",
  email_consent: "unknown",
  do_not_call: "",
  preferred_language: "",
  ...over,
});

describe("account form rules (mirror the API)", () => {
  it("turns empty optional fields into null and drops them on create", () => {
    const parsed = accountSchema.parse(account({ name: "  Example Co " }));
    expect(parsed.name).toBe("Example Co");
    expect(parsed.segment).toBeNull();
    expect(withoutNulls(parsed)).toEqual({
      name: "Example Co",
      account_type: "company",
    });
  });

  it.each([
    ["website", "javascript:alert(1)"],
    ["website", "not a url"],
    ["phone", "call me"],
    ["segment", "huge"],
    ["parent_account_id", "../../admin"],
    ["name", ""],
    ["country", "India"],
    ["preferred_language", "english"],
    ["lifecycle_stage", "vip"],
    ["account_type", "store"],
  ])("refuses a bad %s", (field, value) => {
    const result = accountSchema.safeParse(account({ [field]: value }));
    expect(result.success).toBe(false);
  });

  it("accepts web addresses with or without https://", () => {
    for (const website of [
      "https://example.com",
      "example.com/about",
      "http://example.com:8080",
    ])
      expect(accountSchema.safeParse(account({ website })).success).toBe(true);
  });
});

describe("contact form rules (mirror the API)", () => {
  it("reads checkboxes: unticked means false", () => {
    const form = new FormData();
    form.set("last_name", "Example");
    form.set("is_primary__present", "1");
    form.set("do_not_call__present", "1");
    form.set("do_not_call", "on");
    const values = withCheckboxes(
      readForm(form, ["last_name", "is_primary", "do_not_call", "owner_id"]),
      form,
      ["is_primary", "do_not_call"],
    );
    expect(values).toEqual({
      last_name: "Example",
      is_primary: "",
      do_not_call: "on",
    });
    // owner_id wasn't in the form at all, so it is never sent.
    expect("owner_id" in values).toBe(false);
  });

  it("a primary contact needs an account", () => {
    const alone = contactSchema.safeParse(contact({ is_primary: "on" }));
    expect(alone.success).toBe(false);
    const linked = contactSchema.parse(
      contact({ is_primary: "on", account_id: ACCOUNT }),
    );
    expect([linked.is_primary, linked.account_id]).toEqual([true, ACCOUNT]);
  });

  it.each([
    ["email", "nope"],
    ["mobile", "+44 abc"],
    ["email_consent", "maybe"],
    ["account_id", "not-an-id"],
  ])("refuses a bad %s", (field, value) => {
    expect(contactSchema.safeParse(contact({ [field]: value })).success).toBe(
      false,
    );
  });
});

describe("history lines", () => {
  const entry = (
    action: string,
    changes: Record<string, unknown>,
  ): TimelineEntry => ({
    at: "2026-10-19T08:00:00Z",
    action,
    title: "x",
    changes,
    actor_name: "Avery Agent",
  });

  it("shows old → new with readable labels, and hides raw IDs", () => {
    expect(
      describeChanges(
        entry("account.updated", {
          segment: { old: "enterprise", new: "mid_market" },
          owner_id: { old: "a", new: "b" },
          parent_account_id: { old: "a", new: null },
        }),
      ),
    ).toEqual([
      "Segment: Enterprise → Mid-market",
      "Owner set",
      "Parent account removed",
    ]);
  });

  it("lists only filled fields on creation, plus reasons and contact names", () => {
    expect(
      describeChanges(
        entry("contact.created", {
          last_name: { old: null, new: "Example" },
          email: { old: null, new: null },
          do_not_call: { old: null, new: false },
          email_consent: { old: null, new: "granted" },
        }),
      ),
    ).toEqual(["Last name: Example", "E-mail consent: Agreed to e-mails"]);
    expect(
      describeChanges(entry("account.deactivated", { reason: "Closed" })),
    ).toEqual(["Reason: Closed"]);
    expect(
      describeChanges(
        entry("account.contact_added", {
          contact_id: "x",
          contact_name: "Sam Sample",
        }),
      ),
    ).toEqual(["Sam Sample"]);
  });
});

describe("relationship timeline", () => {
  it("merges real records newest first and skips drafts and unconverted leads", () => {
    const events = relationshipTimeline({
      audit: [
        {
          at: "2026-10-01T10:00:00Z",
          action: "account.created",
          title: "Account created",
          changes: {},
          actor_name: "Avery",
        },
      ],
      orders: [
        {
          id: "o1",
          number: 7,
          created_at: "2026-10-05T09:00:00Z",
          total: "10.00",
          currency: "EUR",
          status: "in_fulfilment",
        },
      ],
      invoices: [
        {
          id: "i1",
          number: 3,
          issue_date: "2026-10-06",
          total: "10.00",
          currency: "EUR",
        },
        {
          id: "i2",
          number: null,
          issue_date: null,
          total: "5.00",
          currency: "EUR",
        },
      ],
      tickets: [
        {
          id: "t1",
          number: 12,
          created_at: "2026-10-04T12:00:00Z",
          subject: "Broken",
        },
      ],
      leads: [
        {
          id: "l1",
          first_name: "Sam",
          last_name: "Sample",
          converted_at: "2026-10-02T08:00:00Z",
        },
        { id: "l2", first_name: null, last_name: "Open", converted_at: null },
      ],
    });
    expect(events.map((e) => [e.title, e.href ?? null])).toEqual([
      ["Invoice INV-0003 issued", "/invoices/i1"],
      ["Order SO-0007 created", "/orders/o1"],
      ["Support ticket T-0012 opened", "/tickets/t1"],
      ["Lead converted: Sam Sample", "/leads/l1"],
      ["Account created", null],
    ]);
    expect(events[1].details).toEqual(["10.00 EUR · now in fulfilment"]);
  });

  it("keeps only the newest entries", () => {
    const tickets = Array.from({ length: 40 }, (_, n) => ({
      id: `t${n}`,
      number: n,
      created_at: new Date(Date.UTC(2026, 0, 1 + n)).toISOString(),
      subject: "x",
    }));
    const events = relationshipTimeline({ tickets }, 30);
    expect(events).toHaveLength(30);
    expect(events[0].title).toBe("Support ticket T-0039 opened");
  });
});

describe("contact list URL parameters", () => {
  it("keeps valid values, drops invalid ones and builds links", () => {
    const p = parseContactParams({ q: " sam ", consent: "granted", page: "2" });
    expect(p).toEqual({ q: "sam", consent: "granted", page: 2 });
    expect(contactApiQuery(p)).toBe(
      "limit=25&offset=25&q=sam&email_consent=granted",
    );
    expect(contactPageHref(p, 1)).toBe("/contacts?q=sam&consent=granted");
    expect(parseContactParams({ consent: "maybe", page: "-1" })).toEqual({
      q: "",
      consent: "",
      page: 1,
    });
  });
});

describe("new customer fields", () => {
  it("normalises country and language codes", () => {
    const parsed = accountSchema.parse(
      account({
        country: " in ",
        preferred_language: "EN",
        lifecycle_stage: "onboarding",
      }),
    );
    expect([
      parsed.country,
      parsed.preferred_language,
      parsed.lifecycle_stage,
    ]).toEqual(["IN", "en", "onboarding"]);
  });
});
