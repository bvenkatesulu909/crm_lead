import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { LeadActionBar } from "@/app/(app)/leads/[id]/lead-action-bar";
import { ActionDialog } from "@/components/action-dialog";
import { ReplyForm } from "@/components/ticket-forms";
import { ticketNumber } from "@/components/tickets";
import type { LeadStatus } from "@/lib/api-types";
import { type DialogState, initialDialogState } from "@/lib/dialog-state";
import { type FormState, initialFormState } from "@/lib/form-state";
import { availableActions } from "@/lib/lead-rules";
import { STATUS_ACTIONS, nextStatuses } from "@/lib/ticket-rules";
import {
  convertPayload,
  convertSchema,
  disqualifySchema,
} from "@/lib/validation/lead-actions";
import { portalTicketSchema } from "@/lib/validation/tickets";

type Action = (state: DialogState, formData: FormData) => Promise<DialogState>;

const AGENT = {
  user_id: "agent",
  permissions: [
    "lead:read:own",
    "lead:write:own",
    "lead:convert",
    "account:write:own",
  ],
};
const MANAGER = {
  user_id: "mgr",
  permissions: [
    "lead:read:all",
    "lead:write:all",
    "lead:assign",
    "lead:convert",
    "account:write:all",
  ],
};
const SUPPORT = { user_id: "sup", permissions: ["account:read:all"] };

const lead = (status: LeadStatus, owner_id: string | null = "agent") => ({
  status,
  owner_id,
});
const shown = (can: Record<string, boolean>) =>
  Object.keys(can)
    .filter((k) => can[k])
    .sort();

describe("which lead actions are offered (display only)", () => {
  it.each([
    ["new", ["disqualify", "edit", "markContacted", "qualify"]],
    ["contacted", ["disqualify", "edit", "qualify"]],
    ["qualified", ["convert", "disqualify", "edit", "markContacted"]],
    ["unqualified", ["edit", "markContacted"]],
    ["converted", []],
  ] as const)("agent on own %s lead: %j", (status, expected) => {
    expect(shown(availableActions(lead(status), AGENT))).toEqual(expected);
  });

  it("agent gets nothing on a colleague's lead", () => {
    expect(
      shown(availableActions(lead("qualified", "someone-else"), AGENT)),
    ).toEqual([]);
  });

  it("manager may also assign, on any lead", () => {
    expect(
      shown(availableActions(lead("new", "someone-else"), MANAGER)),
    ).toContain("assign");
  });

  it("support agents get no lead actions", () => {
    expect(shown(availableActions(lead("qualified"), SUPPORT))).toEqual([]);
  });
});

describe("dialog input rules", () => {
  const base = {
    account_mode: "new",
    create_opportunity: true,
    currency: "eur",
    amount: "1250.5",
  };

  it("disqualify needs a real reason", () => {
    expect(disqualifySchema.safeParse({ reason: "  " }).success).toBe(false);
    expect(disqualifySchema.safeParse({ reason: "No budget" }).success).toBe(
      true,
    );
  });

  it("builds the backend's convert body", () => {
    const data = convertSchema.parse({ ...base, account_name: "" });

    expect(convertPayload(data)).toEqual({
      account: { name: null },
      opportunity: {
        name: null,
        amount: "1250.5",
        currency: "EUR",
        expected_close_date: null,
      },
    });
  });

  it.each([
    [{ amount: "12,50" }, "amount"],
    [{ amount: "1.234" }, "amount"],
    [{ currency: "EURO" }, "currency"],
    [
      { account_mode: "existing", existing_account_id: "" },
      "existing_account_id",
    ],
  ])("rejects %j", (change, field) => {
    const result = convertSchema.safeParse({ ...base, ...change });

    expect(result.success).toBe(false);
    expect(result.error?.issues.map((i) => i.path[0])).toContain(field);
  });

  it("without an opportunity, no currency is needed", () => {
    const data = convertSchema.parse({
      account_mode: "new",
      create_opportunity: false,
      currency: "",
    });

    expect(convertPayload(data).opportunity).toBeNull();
  });
});

describe("ActionDialog (confirmation before changes)", () => {
  const dialog = (
    action: Action,
    initialState: DialogState = initialDialogState,
  ) => (
    <ActionDialog
      triggerLabel="Qualify"
      title="Qualify this lead?"
      description="Explains what happens."
      confirmLabel="Qualify lead"
      action={action}
      initialState={initialState}
    />
  );

  it("does nothing until the user confirms, and Cancel changes nothing", async () => {
    const action = vi.fn<Action>(async (s) => s);
    const user = userEvent.setup();
    render(dialog(action));

    await user.click(screen.getByRole("button", { name: "Qualify" }));
    const open = screen.getByRole("dialog", { name: "Qualify this lead?" });
    expect(open).toHaveAccessibleDescription("Explains what happens.");
    await user.click(within(open).getByRole("button", { name: "Cancel" }));

    expect(action).not.toHaveBeenCalled();
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("runs the action on confirm", async () => {
    const action = vi.fn<Action>(async (s) => s);
    const user = userEvent.setup();
    render(dialog(action));

    await user.click(screen.getByRole("button", { name: "Qualify" }));
    await user.click(screen.getByRole("button", { name: "Qualify lead" }));

    expect(action).toHaveBeenCalledOnce();
  });

  it("stays open and shows the API's explanation when the action fails", () => {
    const failed: DialogState = {
      attempt: 1,
      fieldErrors: {},
      error: {
        status: 409,
        message: "A lead cannot go from 'unqualified' to 'qualified'.",
        code: "invalid_status_transition",
        requestId: "r1",
        fieldErrors: {},
      },
    };
    render(dialog(vi.fn<Action>(), failed));

    const open = screen.getByRole("dialog", { name: "Qualify this lead?" });
    expect(within(open).getByRole("alert")).toHaveTextContent(
      "cannot go from 'unqualified'",
    );
  });
});

describe("LeadActionBar", () => {
  const noop = vi.fn<Action>(async (s) => s);
  const actions = {
    assign: noop,
    markContacted: noop,
    qualify: noop,
    disqualify: noop,
    convert: noop,
  };
  const summary = {
    id: "11111111-1111-4111-8111-111111111111",
    name: "Jamie Example",
    company: "Example Ltd",
    ownerId: "a",
    ownerName: "Avery",
  };
  const none = {
    edit: false,
    assign: false,
    markContacted: false,
    qualify: false,
    disqualify: false,
    convert: false,
  };

  it("renders only the allowed buttons, as a labelled group", () => {
    render(
      <LeadActionBar
        lead={summary}
        assignees={[]}
        accounts={[]}
        actions={actions}
        can={{ ...none, edit: true, qualify: true, disqualify: true }}
      />,
    );

    const group = screen.getByRole("group", { name: "Lead actions" });
    expect(
      within(group)
        .getAllByRole("button")
        .map((b) => b.textContent),
    ).toEqual(["Qualify", "Disqualify"]);
    expect(within(group).getByRole("link", { name: "Edit" })).toHaveAttribute(
      "href",
      `/leads/${summary.id}/edit`,
    );
  });

  it("assign dialog never offers the current owner", async () => {
    const user = userEvent.setup();
    render(
      <LeadActionBar
        lead={summary}
        accounts={[]}
        actions={actions}
        assignees={[
          { id: "a", display_name: "Avery", assignable: true, support: false },
          { id: "b", display_name: "Blake", assignable: true, support: false },
        ]}
        can={{ ...none, assign: true }}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Assign" }));
    const options = within(screen.getByLabelText("New owner"))
      .getAllByRole("option")
      .map((o) => o.textContent);
    expect(options).toEqual(["Choose a sales employee…", "Blake"]);
  });

  it("convert dialog warns that it cannot be undone", async () => {
    const user = userEvent.setup();
    render(
      <LeadActionBar
        lead={summary}
        assignees={[]}
        accounts={[]}
        actions={actions}
        can={{ ...none, convert: true }}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Convert" }));
    const open = screen.getByRole("dialog", { name: "Convert this lead" });
    expect(open).toHaveTextContent("This cannot be undone.");
    // No accounts available to this user: the "existing account" option is disabled.
    expect(
      within(open).getByLabelText(/Link to an existing account/),
    ).toBeDisabled();
  });

  it("shows nothing when no action is allowed", () => {
    const { container } = render(
      <LeadActionBar
        lead={summary}
        assignees={[]}
        accounts={[]}
        actions={actions}
        can={none}
      />,
    );

    expect(container).toBeEmptyDOMElement();
  });
});

describe("support tickets (display rules and input checks)", () => {
  it("offers only valid next statuses and nothing for closed tickets", () => {
    expect(nextStatuses("new")).toEqual([
      "open",
      "pending_customer",
      "resolved",
      "closed",
    ]);
    expect(nextStatuses("resolved")).toEqual(["open", "closed"]);
    expect(nextStatuses("closed")).toEqual([]);
    expect(STATUS_ACTIONS.open.label("new")).toBe("Start work");
    expect(STATUS_ACTIONS.open.label("resolved")).toBe("Reopen");
    expect(STATUS_ACTIONS.closed.danger).toBe(true);
  });

  it("formats ticket numbers", () => {
    expect(ticketNumber(7)).toBe("T-0007");
    expect(ticketNumber(12345)).toBe("T-12345");
  });

  it("validates new tickets like the API", () => {
    const ok = portalTicketSchema.safeParse({
      account_id: "11111111-1111-4111-8111-111111111111",
      subject: "Printer broken",
      description: "It smokes.",
      category: "problem",
    });
    const bad = portalTicketSchema.safeParse({
      account_id: "x",
      subject: "Hi",
      description: " ",
      category: "rant",
    });

    expect(ok.success).toBe(true);
    expect(bad.error?.issues.map((i) => i.path[0]).sort()).toEqual([
      "account_id",
      "category",
      "description",
      "subject",
    ]);
  });
});

describe("ReplyForm", () => {
  type FormAction = (s: FormState, f: FormData) => Promise<FormState>;

  it("makes clear whether staff are writing to the customer or an internal note", async () => {
    const user = userEvent.setup();
    render(
      <ReplyForm
        action={vi.fn<FormAction>()}
        initialState={initialFormState}
        staff
      />,
    );

    expect(
      screen.getByRole("button", { name: "Send reply to customer" }),
    ).toBeInTheDocument();
    await user.click(screen.getByLabelText("Internal note (staff only)"));
    expect(
      screen.getByRole("button", { name: "Add internal note" }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Internal note")).toBeInTheDocument();
  });

  it("customers have no internal option", () => {
    render(
      <ReplyForm
        action={vi.fn<FormAction>()}
        initialState={initialFormState}
      />,
    );

    expect(screen.queryByText(/Internal note/)).toBeNull();
    expect(
      screen.getByRole("button", { name: "Send reply" }),
    ).toBeInTheDocument();
  });
});
