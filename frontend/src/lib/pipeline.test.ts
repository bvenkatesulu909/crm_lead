import { describe, expect, it } from "vitest";

import type { CrmActivity } from "@/lib/api-types";
import {
  dueLabel,
  groupTasks,
  isoToLocal,
  localToIso,
  monthGrid,
  parseMonth,
} from "@/lib/pipeline";
import {
  activityPayload,
  activitySchema,
  opportunitySchema,
} from "@/lib/validation/pipeline";

const NOW = new Date("2026-10-19T10:00:00Z");

function task(over: Partial<CrmActivity>): CrmActivity {
  return {
    id: Math.random().toString(36),
    kind: "task",
    subject: "x",
    body: null,
    status: "open",
    priority: "normal",
    due_at: null,
    reminder_at: null,
    completed_at: null,
    outcome: null,
    overdue: false,
    assignee_id: "u",
    created_by_user_id: "u",
    related_type: null,
    related_id: null,
    created_at: NOW.toISOString(),
    updated_at: NOW.toISOString(),
    version: 1,
    ...over,
  };
}

describe("due labels", () => {
  it.each([
    ["2026-10-19T10:30:00Z", "Due in 30 minutes"],
    ["2026-10-19T13:00:00Z", "Due in 3 hours"],
    ["2026-10-23T10:00:00Z", "Due in 4 days"],
    ["2026-10-19T09:59:30Z", "Overdue by 1 minute"],
    ["2026-10-17T10:00:00Z", "Overdue by 2 days"],
    ["2026-10-14T10:00:00Z", "Overdue by 5 days"],
    ["2026-10-17T12:00:00Z", "Overdue by 46 hours"],
  ])("%s -> %s", (due, label) => {
    expect(dueLabel(due, NOW)).toBe(label);
  });
});

describe("grouping open tasks by the viewer's local day", () => {
  it("puts each open item in exactly one group and skips finished ones", () => {
    const now = new Date(2026, 9, 19, 10, 0); // local 10:00
    const at = (h: number, day = 19) =>
      new Date(2026, 9, day, h, 0).toISOString();
    const groups = groupTasks(
      [
        task({ subject: "late", due_at: at(9) }),
        task({ subject: "later today", due_at: at(18) }),
        task({ subject: "tomorrow", due_at: at(9, 20) }),
        task({ subject: "someday" }),
        task({
          subject: "finished",
          status: "done",
          due_at: at(9),
          completed_at: at(9),
        }),
      ],
      now,
    );
    const names = Object.fromEntries(
      Object.entries(groups).map(([k, v]) => [
        k,
        v.map((t: CrmActivity) => t.subject),
      ]),
    );
    expect(names).toEqual({
      overdue: ["late"],
      today: ["later today"],
      upcoming: ["tomorrow"],
      someday: ["someday"],
    });
  });
});

describe("local date/time conversion", () => {
  it("round-trips a datetime-local value", () => {
    const iso = localToIso("2026-10-19T09:30");
    expect(iso).toMatch(/Z$/);
    expect(isoToLocal(iso)).toBe("2026-10-19T09:30");
  });

  it("returns empty for empty or invalid input", () => {
    expect(localToIso("")).toBe("");
    expect(localToIso("not a date")).toBe("");
    expect(isoToLocal(null)).toBe("");
  });
});

describe("month calendar", () => {
  it("starts on Monday and covers the whole month", () => {
    const days = monthGrid(2026, 9); // October 2026 starts on a Thursday
    expect(days[0].getDay()).toBe(1);
    expect(days[0].getDate()).toBe(28); // Monday 28 September
    expect(days.length % 7).toBe(0);
    expect(days.some((d) => d.getMonth() === 9 && d.getDate() === 31)).toBe(
      true,
    );
  });

  it("reads ?month= safely", () => {
    const fallback = new Date(2026, 9, 19);
    expect(parseMonth("2027-02", fallback)).toEqual([2027, 1]);
    expect(parseMonth("2027-13", fallback)).toEqual([2026, 9]);
    expect(parseMonth("../../etc", fallback)).toEqual([2026, 9]);
    expect(parseMonth(undefined, fallback)).toEqual([2026, 9]);
  });
});

describe("opportunity form rules", () => {
  const base = {
    name: "50 licences",
    account_id: "ac000000-0000-4000-8000-0000000000a1",
    primary_contact_id: "",
    amount: "",
    currency: "eur",
    expected_close_date: "",
    next_step: "",
    description: "",
  };

  it("normalises the currency and empties", () => {
    const parsed = opportunitySchema.parse(base);
    expect([parsed.currency, parsed.amount, parsed.primary_contact_id]).toEqual(
      ["EUR", null, null],
    );
  });

  it.each([
    ["amount", "-5"],
    ["amount", "1.234"],
    ["amount", "12,50"],
    ["currency", "EURO"],
    ["account_id", ""],
    ["expected_close_date", "next week"],
  ])("refuses a bad %s", (field, value) => {
    expect(
      opportunitySchema.safeParse({ ...base, [field]: value }).success,
    ).toBe(false);
  });
});

describe("activity form rules", () => {
  const base = {
    kind: "task",
    subject: "Call back",
    body: "",
    status: "open",
    priority: "normal",
    due_at: "2030-01-02T09:00:00.000Z",
    reminder_at: "2030-01-02T08:00:00.000Z",
    occurred_at: "",
    outcome: "",
  };

  it("sends only what fits the item: plan vs log", () => {
    const planned = activityPayload(activitySchema.parse(base));
    expect(planned).toEqual({
      kind: "task",
      subject: "Call back",
      body: null,
      status: "open",
      priority: "normal",
      due_at: "2030-01-02T09:00:00.000Z",
      reminder_at: "2030-01-02T08:00:00.000Z",
    });
    const logged = activityPayload(
      activitySchema.parse({
        ...base,
        kind: "call",
        status: "done",
        outcome: "Interested",
      }),
    );
    expect(logged).toEqual({
      kind: "call",
      subject: "Call back",
      body: null,
      status: "done",
      outcome: "Interested",
    });
  });

  it.each([
    [{ kind: "note", status: "open" }, "kind"],
    [{ reminder_at: "2030-01-03T09:00:00.000Z" }, "reminder_at"],
    [
      { status: "done", occurred_at: "2999-01-01T00:00:00.000Z" },
      "occurred_at",
    ],
    [{ due_at: "2030-01-02T09:00" }, "due_at"], // no time zone
    [{ subject: "" }, "subject"],
  ])("refuses %j", (change, field) => {
    const result = activitySchema.safeParse({ ...base, ...change });
    expect(result.success).toBe(false);
    expect(result.error?.issues.map((i) => i.path[0])).toContain(field);
  });
});
