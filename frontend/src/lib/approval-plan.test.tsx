import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import nextConfig from "../../next.config";
import { ApprovalCard } from "@/components/approval-views";
import type { AgentAction } from "@/lib/api-types";
import { describeChange } from "@/lib/approvals";

const ME = "11111111-1111-4111-8111-111111111111";
const AVERY = "22222222-2222-4222-8222-222222222222";
const MAYA = "33333333-3333-4333-8333-333333333333";
const people = { [AVERY]: "Avery Agent", [MAYA]: "Maya Manager" };

function action(changes: Partial<AgentAction> = {}): AgentAction {
  return {
    id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    kind: "lead.set_status",
    description: "Change the lead's status to contacted",
    target_type: "lead",
    target_id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
    target_link: "/leads/bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
    target_label: "Asha Rao",
    payload: { status: "contacted" },
    reason: "She answered my call today.",
    agent: "staff_assistant",
    requested_by_user_id: AVERY,
    status: "pending",
    expires_at: "2026-11-01T10:00:00Z",
    decided_by_user_id: null,
    decided_at: null,
    decision_note: null,
    result: null,
    warnings: [],
    changes: [],
    outcome: null,
    created_at: "2026-10-25T10:00:00Z",
    version: 1,
    ...changes,
  };
}

const view = (a: AgentAction) =>
  render(<ApprovalCard action={a} people={people} me={{ user_id: ME }} />);

describe("describeChange", () => {
  const nameOf = (id: string | null) =>
    id ? (people as Record<string, string>)[id] : "";

  it("shows a status change as words", () => {
    expect(
      describeChange(
        { field: "status", before: "new", after: "contacted" },
        nameOf,
      ),
    ).toBe("Status: new → contacted");
  });

  it("shows people by name and a missing owner as nobody", () => {
    expect(
      describeChange({ field: "owner_id", before: null, after: MAYA }, nameOf),
    ).toBe("Owner: nobody → Maya Manager");
  });

  it("shows a new task with its details and who it is for", () => {
    const text = describeChange(
      {
        field: "task",
        before: null,
        after: {
          subject: "Call the buyer",
          due_in_days: 2,
          assignee_id: AVERY,
        },
      },
      nameOf,
    );
    expect(text).toBe(
      "New task: Call the buyer, due in 2 days, for Avery Agent",
    );
  });

  it("never fails on a field it does not know", () => {
    expect(
      describeChange({ field: "mystery", before: 1, after: { a: 1 } }, nameOf),
    ).toContain("mystery");
  });
});

describe("the plan and the outcome on the card", () => {
  it("shows what a waiting proposal would change", () => {
    view(
      action({
        changes: [{ field: "status", before: "new", after: "contacted" }],
      }),
    );
    const box = screen.getByRole("group", { name: "Would change" });
    expect(
      within(box).getByText("Status: new → contacted"),
    ).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "What happened" })).toBeNull();
  });

  it("shows nothing for an old proposal without a plan", () => {
    view(action());
    expect(screen.queryByRole("group", { name: "Would change" })).toBeNull();
  });

  it("says an approved proposal ran as announced", () => {
    view(
      action({
        status: "approved",
        decided_at: "2026-10-26T10:00:00Z",
        decided_by_user_id: MAYA,
        changes: [{ field: "status", before: "new", after: "contacted" }],
        outcome: {
          ran: true,
          matches_plan: true,
          differs: [],
          seen: [{ field: "status", after: "contacted" }],
        },
      }),
    );
    const box = screen.getByRole("group", { name: "What happened" });
    expect(
      within(box).getByText(/matched what was announced/i),
    ).toBeInTheDocument();
  });

  it("names the fields that differed from the plan", () => {
    view(
      action({
        status: "approved",
        decided_at: "2026-10-26T10:00:00Z",
        outcome: {
          ran: true,
          matches_plan: false,
          differs: ["status"],
          seen: [{ field: "status", after: "new" }],
        },
      }),
    );
    const box = screen.getByRole("group", { name: "What happened" });
    expect(within(box).getByText(/did not match/i)).toBeInTheDocument();
    expect(within(box).getByText(/Status/)).toBeInTheDocument();
  });

  it("says when the action did not run", () => {
    view(
      action({
        status: "failed",
        decided_at: "2026-10-26T10:00:00Z",
        outcome: { ran: false, matches_plan: null, differs: [], seen: [] },
      }),
    );
    expect(screen.getByText(/did not run/i)).toBeInTheDocument();
  });

  it("shows text a model wrote as plain text", () => {
    const { container } = view(
      action({
        changes: [
          {
            field: "task",
            before: null,
            after: { subject: "<b>Hi</b>", due_in_days: 1, assignee_id: AVERY },
          },
        ],
      }),
    );
    expect(container.querySelector("b")).toBeNull();
    expect(screen.getByText(/<b>Hi<\/b>/)).toBeInTheDocument();
  });
});

describe("the content security policy (ADR 0018)", () => {
  it("is reported, not enforced, and blocks outside images and plug-ins", async () => {
    const rules = await nextConfig.headers!();
    const headers = rules.flatMap((rule) => rule.headers);
    const names = headers.map((h) => h.key);
    expect(names).not.toContain("Content-Security-Policy");
    const report = headers.find(
      (h) => h.key === "Content-Security-Policy-Report-Only",
    );
    expect(report).toBeDefined();
    const value = report!.value;
    expect(value).toContain("img-src 'self' data:");
    expect(value).toContain("object-src 'none'");
    expect(value).toContain("frame-ancestors 'none'");
    expect(value).toContain("base-uri 'self'");
  });
});
