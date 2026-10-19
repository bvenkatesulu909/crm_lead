import { describe, expect, it } from "vitest";

import {
  dashboardHref,
  dashboardQuery,
  formatAmounts,
  formatPeriod,
  formatRate,
  hasDashboard,
  parseDashboardFilters,
  rangeDates,
} from "@/lib/dashboard";

// 18 Oct 2026, late evening UTC (already 19 Oct in India): the dashboard counts in UTC.
const TODAY = new Date("2026-10-18T22:30:00Z");
const REP = "a1000000-0000-4000-8000-000000000003";

describe("dashboard period presets", () => {
  it.each([
    ["7d", "2026-10-12"],
    ["30d", "2026-09-19"],
    ["90d", "2026-07-21"],
    ["month", "2026-10-01"],
    ["year", "2026-01-01"],
  ] as const)("%s starts on %s and ends today", (range, start) => {
    expect(rangeDates(range, TODAY)).toEqual([start, "2026-10-18"]);
  });
});

describe("parseDashboardFilters", () => {
  it("defaults to the last 30 days, widest view, whole team", () => {
    expect(parseDashboardFilters({}, TODAY)).toEqual({
      range: "30d",
      start: "2026-09-19",
      end: "2026-10-18",
      view: "",
      rep: "",
    });
  });

  it("uses custom dates only when both are valid", () => {
    const custom = parseDashboardFilters(
      { range: "custom", from: "2026-01-01", to: "2026-01-31" },
      TODAY,
    );
    expect([custom.range, custom.start, custom.end]).toEqual([
      "custom",
      "2026-01-01",
      "2026-01-31",
    ]);
    for (const bad of [
      { range: "custom", from: "2026-01-01" },
      { range: "custom", from: "2026-02-30x", to: "2026-03-01" },
      { range: "custom", from: "yesterday", to: "today" },
    ]) {
      expect(parseDashboardFilters(bad, TODAY).range).toBe("30d");
    }
  });

  it("a preset wins over leftover dates from the form", () => {
    const f = parseDashboardFilters(
      { range: "7d", from: "2026-01-01", to: "2026-01-31" },
      TODAY,
    );
    expect([f.range, f.start]).toEqual(["7d", "2026-10-12"]);
  });

  it("ignores unknown views, ranges and malformed rep IDs", () => {
    const f = parseDashboardFilters(
      { view: "god", range: "forever", rep: "1 OR 1=1" },
      TODAY,
    );
    expect([f.view, f.range, f.rep]).toEqual(["", "30d", ""]);
    expect(parseDashboardFilters({ rep: REP.toUpperCase() }, TODAY).rep).toBe(
      REP,
    );
  });
});

describe("dashboard links and API query", () => {
  const base = parseDashboardFilters({}, TODAY);

  it("sends dates, view and rep to the API", () => {
    const q = new URLSearchParams(
      dashboardQuery({ ...base, view: "manager", rep: REP }),
    );
    expect(Object.fromEntries(q)).toEqual({
      start: "2026-09-19",
      end: "2026-10-18",
      view: "manager",
      owner_id: REP,
    });
  });

  it("never sends a rep filter for the own-sales view", () => {
    const q = new URLSearchParams(
      dashboardQuery({ ...base, view: "representative", rep: REP }),
    );
    expect(q.has("owner_id")).toBe(false);
  });

  it("builds short, shareable URLs", () => {
    expect(dashboardHref(base, {})).toBe("/");
    expect(dashboardHref(base, { range: "month" })).toBe("/?range=month");
    expect(
      dashboardHref(base, {
        range: "custom",
        start: "2026-01-01",
        end: "2026-01-31",
        rep: REP,
      }),
    ).toBe(`/?range=custom&from=2026-01-01&to=2026-01-31&rep=${REP}`);
    expect(
      dashboardHref({ ...base, rep: REP }, { view: "representative" }),
    ).toBe("/?view=representative");
  });
});

describe("dashboard formatting", () => {
  it("keeps currencies apart and shows a dash for nothing", () => {
    expect(formatAmounts([])).toBe("—");
    expect(
      formatAmounts([
        { currency: "EUR", amount: "1500.50" },
        { currency: "USD", amount: "20.00" },
      ]),
    ).toBe("€1,500.50 · US$20.00");
  });

  it("formats rates and periods", () => {
    expect(formatRate(null)).toBe("—");
    expect(formatRate(0.2126)).toBe("21.3%");
    expect(formatPeriod("2026-01-01", "2026-01-31")).toBe(
      "1 Jan 2026 – 31 Jan 2026",
    );
    expect(formatPeriod("2026-01-01", "2026-01-01")).toBe("1 Jan 2026");
  });

  it("shows the dashboard only to roles that have one", () => {
    expect(hasDashboard({ permissions: ["dashboard:sales:own"] })).toBe(true);
    expect(hasDashboard({ permissions: ["ticket:read:all"] })).toBe(false);
  });
});
