import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  ApprovalCard,
  ApprovalStatusBadge,
  RecordProposalsList,
} from "@/components/approval-views";
import type { AgentAction, Me } from "@/lib/api-types";
import {
  APPROVAL_STATUS_LABELS,
  approvalPageHref,
  approvalQuery,
  canDecideOn,
  checkDecisionNote,
  decisionErrorText,
  parseApprovalFilters,
} from "@/lib/approvals";
import { modulesFor } from "@/lib/modules";
import {
  canApproveActions,
  canReadApprovals,
  navigationFor,
} from "@/lib/permissions";

const ME = "11111111-1111-4111-8111-111111111111";
const OTHER = "22222222-2222-4222-8222-222222222222";

function me(permissions: string[], userId: string | null = ME): Me {
  return {
    user_id: userId,
    display_name: "Test",
    email: null,
    tenant_id: "t",
    tenant_name: "T",
    user_type: "staff",
    roles: [],
    permissions,
  };
}

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
    requested_by_user_id: OTHER,
    status: "pending",
    expires_at: "2026-11-01T10:00:00Z",
    decided_by_user_id: null,
    decided_at: null,
    decision_note: null,
    result: null,
    warnings: [],
    created_at: "2026-10-25T10:00:00Z",
    version: 1,
    ...changes,
  };
}

// --- permissions, menu, tile (display only; the API decides) ------------------------------

describe("permissions, menu and module tile", () => {
  it("everyone who may propose sees Approvals; only approvers can decide", () => {
    const agent = me(["agent_action:propose"]);
    const manager = me(["agent_action:propose", "agent_action:approve"]);
    expect(canReadApprovals(agent)).toBe(true);
    expect(canApproveActions(agent)).toBe(false);
    expect(canApproveActions(manager)).toBe(true);
    expect(canReadApprovals(me(["lead:read:own"]))).toBe(false);
  });

  it("adds the menu entry and the module tile only for them", () => {
    const labels = (m: Me) => navigationFor(m).map((i) => i.label);
    expect(labels(me(["agent_action:propose"]))).toContain("Approvals");
    expect(labels(me(["lead:read:own"]))).not.toContain("Approvals");
    const tile = (m: Me) => modulesFor(m).find((x) => x.key === "approvals");
    expect(tile(me(["agent_action:propose"]))?.link).toBe("/approvals");
    expect(tile(me(["lead:read:own"]))?.link).toBeUndefined();
  });
});

// --- who may decide, notes, errors ---------------------------------------------------------

describe("canDecideOn", () => {
  const manager = me(["agent_action:approve"]);
  it("needs the permission, a waiting proposal and someone else's request", () => {
    expect(canDecideOn(manager, action())).toBe(true);
    expect(canDecideOn(me(["agent_action:propose"]), action())).toBe(false);
    expect(canDecideOn(manager, action({ status: "approved" }))).toBe(false);
    expect(canDecideOn(manager, action({ requested_by_user_id: ME }))).toBe(
      false,
    );
  });
});

describe("checkDecisionNote", () => {
  it("makes the note optional for approving and required for rejecting", () => {
    expect(checkDecisionNote("  ", false)).toBeNull();
    expect(checkDecisionNote("", true)).toMatch(/why/i);
    expect(checkDecisionNote("x".repeat(501), true)).toMatch(/500/);
    expect(checkDecisionNote("Call first", true)).toBeNull();
  });
});

describe("decisionErrorText", () => {
  it("explains the API's codes in plain words", () => {
    expect(decisionErrorText("agent_action_already_decided")).toMatch(
      /already decided/i,
    );
    expect(decisionErrorText("agent_action_changed")).toMatch(/reload/i);
    expect(decisionErrorText("agent_action_expired")).toMatch(/expired/i);
    expect(decisionErrorText("self_approval_forbidden")).toMatch(/your own/i);
    expect(decisionErrorText("record_not_found")).toMatch(/can't see/i);
    expect(decisionErrorText("something_new", "Original text")).toBe(
      "Original text",
    );
  });
});

// --- the list filters ---------------------------------------------------------------------

describe("filters", () => {
  it("reads the tab, status and page from the address, ignoring junk", () => {
    expect(parseApprovalFilters({})).toEqual({
      tab: "waiting",
      status: "",
      page: 1,
    });
    expect(
      parseApprovalFilters({ tab: "mine", status: "approved", page: "3" }),
    ).toEqual({
      tab: "mine",
      status: "approved",
      page: 3,
    });
    expect(
      parseApprovalFilters({ tab: "x", status: "lost", page: "-4" }),
    ).toEqual({
      tab: "waiting",
      status: "",
      page: 1,
    });
  });

  it("builds the API query: waiting = pending, mine = my own, history = the rest", () => {
    const q = (raw: Record<string, string>) =>
      approvalQuery(parseApprovalFilters(raw), 20).toString();
    expect(q({})).toBe("limit=20&offset=0&status=pending");
    expect(q({ tab: "mine", page: "2" })).toBe("limit=20&offset=20&mine=true");
    expect(q({ tab: "all", status: "rejected" })).toBe(
      "limit=20&offset=0&status=rejected",
    );
    expect(q({ tab: "all" })).toBe("limit=20&offset=0");
  });

  it("keeps the filters in page links", () => {
    expect(approvalPageHref({ tab: "waiting", status: "", page: 1 }, 1)).toBe(
      "/approvals",
    );
    expect(approvalPageHref({ tab: "all", status: "failed", page: 1 }, 3)).toBe(
      "/approvals?tab=all&status=failed&page=3",
    );
  });
});

// --- the screens' parts ---------------------------------------------------------------------

describe("ApprovalStatusBadge", () => {
  it("shows a word, not just a colour, for every status", () => {
    for (const status of Object.keys(
      APPROVAL_STATUS_LABELS,
    ) as AgentAction["status"][]) {
      const { unmount } = render(<ApprovalStatusBadge status={status} />);
      expect(
        screen.getByText(APPROVAL_STATUS_LABELS[status]),
      ).toBeInTheDocument();
      unmount();
    }
  });
});

describe("ApprovalCard", () => {
  const people = { [OTHER]: "Avery Agent", [ME]: "Morgan Manager" };

  it("shows what, where, why, who and when - as plain text", () => {
    const { container } = render(
      <ApprovalCard
        action={action({ reason: "<b>Hurry</b> please" })}
        people={people}
        me={me(["agent_action:approve"])}
      />,
    );
    const card = screen.getByRole("article", {
      name: "Change the lead's status to contacted",
    });
    expect(
      within(card).getByRole("link", { name: "Asha Rao" }),
    ).toHaveAttribute("href", "/leads/bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb");
    expect(within(card).getByText(/Avery Agent/)).toBeInTheDocument();
    expect(within(card).getByText(/<b>Hurry<\/b> please/)).toBeInTheDocument();
    expect(container.querySelector("b")).toBeNull();
    expect(within(card).getByText("Waiting")).toBeInTheDocument();
  });

  it("shows no safety check when there is nothing to check", () => {
    render(<ApprovalCard action={action()} people={people} me={me([])} />);
    expect(screen.queryByText("Safety check")).toBeNull();
  });

  it("shows the safety check above the buttons, one line per warning", () => {
    render(
      <ApprovalCard
        action={action({
          warnings: [
            {
              code: "lead_owned_by_other",
              message: "Someone else owns this lead.",
            },
            {
              code: "record_contains_instruction",
              message:
                "This record contains text that looks like an instruction to an AI.",
            },
          ],
        })}
        people={people}
        me={me(["agent_action:approve"])}
        decision={<button>Approve</button>}
      />,
    );
    const box = screen.getByRole("group", { name: "Safety check" });
    expect(
      within(box).getByText("Check this before you decide:"),
    ).toBeInTheDocument();
    const items = within(box).getAllByRole("listitem");
    expect(items.map((i) => i.textContent)).toEqual([
      "Someone else owns this lead.",
      "This record contains text that looks like an instruction to an AI.",
    ]);
    const button = screen.getByRole("button", { name: "Approve" });
    expect(
      box.compareDocumentPosition(button) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  it("shows warning text as plain text, not markup", () => {
    const { container } = render(
      <ApprovalCard
        action={action({
          warnings: [
            { code: "x", message: "<img src=x onerror=alert(1)> beware" },
          ],
        })}
        people={people}
        me={me([])}
      />,
    );
    expect(screen.getByText(/<img src=x/)).toBeInTheDocument();
    expect(container.querySelector("img")).toBeNull();
  });

  it("keeps the safety check on a decided proposal, as part of its history", () => {
    render(
      <ApprovalCard
        action={action({
          status: "approved",
          decided_by_user_id: ME,
          decided_at: "2026-10-26T10:00:00Z",
          warnings: [
            {
              code: "busy_record",
              message: "Several proposals were made for this record today.",
            },
          ],
        })}
        people={people}
        me={me([])}
      />,
    );
    expect(
      screen.getByRole("group", { name: "Safety check" }),
    ).toBeInTheDocument();
  });

  it("says when the record isn't visible to the reader, without naming it", () => {
    render(
      <ApprovalCard
        action={action({ target_label: null })}
        people={people}
        me={me([])}
      />,
    );
    expect(screen.getByText(/record you can't see/i)).toBeInTheDocument();
  });

  it("explains a decision, a failure and an expiry", () => {
    const { rerender } = render(
      <ApprovalCard
        action={action({
          status: "failed",
          decided_by_user_id: ME,
          decided_at: "2026-10-26T10:00:00Z",
          result: "A lead cannot go from 'contacted' to 'contacted'.",
        })}
        people={people}
        me={me([], "33333333-3333-4333-8333-333333333333")}
      />,
    );
    expect(screen.getByText(/Could not be carried out/)).toBeInTheDocument();
    expect(screen.getByText(/cannot go from/)).toBeInTheDocument();
    expect(screen.getByText(/Morgan Manager/)).toBeInTheDocument();
    rerender(
      <ApprovalCard
        action={action({
          status: "expired",
          decided_at: "2026-11-01T10:00:00Z",
        })}
        people={people}
        me={me([])}
      />,
    );
    expect(screen.getByText("Expired")).toBeInTheDocument();
  });
});

describe("RecordProposalsList", () => {
  it("lists only what is waiting for this record, with links to the cards", () => {
    render(
      <RecordProposalsList
        items={[
          action(),
          action({
            id: "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
            status: "approved",
          }),
        ]}
      />,
    );
    const region = screen.getByRole("region", { name: "AI proposals" });
    const links = within(region).getAllByRole("link");
    expect(links).toHaveLength(1);
    expect(links[0]).toHaveAttribute(
      "href",
      "/approvals/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    );
    expect(links[0]).toHaveTextContent("Change the lead's status to contacted");
  });

  it("is left out when nothing is waiting", () => {
    const { container } = render(
      <RecordProposalsList items={[action({ status: "rejected" })]} />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});
