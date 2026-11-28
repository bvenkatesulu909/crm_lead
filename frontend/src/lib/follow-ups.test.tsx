import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { approveProposal, rejectProposal } from "@/app/(app)/approvals/actions";
import { saveFollowUpSettings } from "@/app/(app)/automation/follow-ups/actions";
import { ApprovalDecision } from "@/components/approval-decision";
import { ApprovalCard, RecordProposalsList } from "@/components/approval-views";
import { FollowUpSettingsForm } from "@/components/follow-up-settings-form";
import { ApiError } from "@/lib/api-error";
import type { AgentAction, Me } from "@/lib/api-types";
import {
  canDecideOn,
  decisionErrorText,
  describeChange,
} from "@/lib/approvals";
import {
  checkSettings,
  FOLLOW_UP_KIND,
  followUpDraft,
  settingsErrorText,
  type FollowUpSettings,
} from "@/lib/follow-ups";
import { initialFormState } from "@/lib/form-state";
import {
  canManageFollowUps,
  navigationFor,
  PERMISSION_LABELS,
} from "@/lib/permissions";

const apiFetch = vi.fn();
vi.mock("@/lib/server/api", () => ({
  apiFetch: (...a: unknown[]) => apiFetch(...a),
}));
vi.mock("next/navigation", () => ({
  redirect: (to: string) => {
    throw new Error(`REDIRECT:${to}`);
  },
}));

beforeEach(() => apiFetch.mockReset());

const ME = "11111111-1111-4111-8111-111111111111";
const OTHER = "22222222-2222-4222-8222-222222222222";
const TEMPLATE = "33333333-3333-4333-8333-333333333333";
const ACTION = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";

function me(permissions: string[]): Me {
  return {
    user_id: ME,
    display_name: "Test",
    email: null,
    tenant_id: "t",
    tenant_name: "T",
    user_type: "staff",
    roles: [],
    permissions,
  };
}

function draft(changes: Partial<AgentAction> = {}): AgentAction {
  return {
    id: ACTION,
    kind: FOLLOW_UP_KIND,
    description: "Send a follow-up e-mail",
    target_type: "lead",
    target_id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
    target_link: "/leads/bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
    target_label: "Asha Rao",
    payload: {
      reason_code: "task_due_today",
      subject: "Checking in <b>today</b>",
      body: "Hello Asha,\n\nIs Saturday still good?",
    },
    reason: "A follow-up task for this lead is due today.",
    agent: "follow_up",
    via_client: null,
    custom_agent_key: null,
    custom_agent_name: null,
    requested_by_user_id: OTHER,
    status: "pending",
    expires_at: "2026-11-30T10:00:00Z",
    decided_by_user_id: null,
    decided_at: null,
    decision_note: null,
    result: null,
    warnings: [],
    changes: [
      {
        field: "email",
        before: null,
        after: { subject: "Checking in", body: "Hello" },
      },
    ],
    outcome: null,
    created_at: "2026-11-22T10:00:00Z",
    version: 4,
    ...changes,
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

function form(values: Record<string, string>): FormData {
  const data = new FormData();
  for (const [k, v] of Object.entries(values)) data.set(k, v);
  return data;
}

const GOOD = {
  enabled: "on",
  template_id: TEMPLATE,
  monthly_cap: "3",
  daily_cap: "50",
  pending_cap: "10",
  expiry_days: "7",
  cooldown_days: "7",
};

const SETTINGS: FollowUpSettings = {
  enabled: false,
  monthly_cap: 3,
  daily_cap: 100,
  pending_cap: 20,
  expiry_days: 7,
  cooldown_days: 7,
  template_id: null,
  template_name: null,
  rule: "task_due_today",
  version: 0,
};

// --- the settings, checked before the API is called -----------------------------------------

describe("checkSettings", () => {
  it("accepts good settings and turns them into numbers", () => {
    const result = checkSettings(GOOD);
    expect(result).toEqual({
      ok: true,
      value: {
        enabled: true,
        template_id: TEMPLATE,
        monthly_cap: 3,
        daily_cap: 50,
        pending_cap: 10,
        expiry_days: 7,
        cooldown_days: 7,
      },
    });
  });

  it.each([
    ["monthly_cap", "0"],
    ["monthly_cap", "9"],
    ["daily_cap", "101"],
    ["pending_cap", "21"],
    ["expiry_days", "31"],
    ["cooldown_days", "0"],
    ["cooldown_days", "61"],
    ["daily_cap", "abc"],
    ["daily_cap", "5.5"],
    ["daily_cap", "-1"],
    ["daily_cap", ""],
  ])("refuses %s = %s", (name, value) => {
    const result = checkSettings({ ...GOOD, [name]: value });
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.errors[name]).toMatch(/whole number from/);
  });

  it("switching on needs a template; switching off does not", () => {
    const on = checkSettings({ ...GOOD, template_id: "" });
    expect(on.ok).toBe(false);
    if (!on.ok) expect(on.errors.template_id).toMatch(/Choose a template/);
    const off = checkSettings({ ...GOOD, enabled: "", template_id: "" });
    expect(off).toMatchObject({ ok: true, value: { enabled: false } });
  });

  it("refuses a template that is not an id", () => {
    expect(checkSettings({ ...GOOD, template_id: "x" }).ok).toBe(false);
  });

  it("explains the API's own refusals in plain words", () => {
    expect(settingsErrorText("version_conflict")).toMatch(/Reload/);
    expect(settingsErrorText("follow_up_settings_invalid")).toMatch(/template/);
    expect(settingsErrorText(undefined, "Server words")).toBe("Server words");
  });
});

describe("the Server Action", () => {
  const previous = initialFormState;

  it("sends the checked settings and the version, then goes back to the page", async () => {
    apiFetch.mockResolvedValueOnce({});
    await expect(saveFollowUpSettings(5, previous, form(GOOD))).rejects.toThrow(
      "REDIRECT:/automation/follow-ups?done=saved",
    );
    const [path, init] = apiFetch.mock.calls[0];
    expect(path).toBe("/communications/follow-up-settings");
    expect(init.method).toBe("PUT");
    expect(JSON.parse(init.body)).toEqual({
      enabled: true,
      template_id: TEMPLATE,
      monthly_cap: 3,
      daily_cap: 50,
      pending_cap: 10,
      expiry_days: 7,
      cooldown_days: 7,
      version: 5,
    });
  });

  it("sends nothing the form did not hold (no tenant, no rule)", async () => {
    apiFetch.mockResolvedValueOnce({});
    await expect(
      saveFollowUpSettings(
        0,
        previous,
        form({ ...GOOD, tenant_id: "x", rule: "y" }),
      ),
    ).rejects.toThrow("REDIRECT");
    expect(
      Object.keys(JSON.parse(apiFetch.mock.calls[0][1].body)).sort(),
    ).toEqual([
      "cooldown_days",
      "daily_cap",
      "enabled",
      "expiry_days",
      "monthly_cap",
      "pending_cap",
      "template_id",
      "version",
    ]);
  });

  it("refuses bad numbers before calling the API and keeps what was typed", async () => {
    const state = await saveFollowUpSettings(
      0,
      previous,
      form({ ...GOOD, daily_cap: "500" }),
    );
    expect(state.fieldErrors.daily_cap).toMatch(/whole number/);
    expect(state.values.daily_cap).toBe("500");
    expect(state.attempt).toBe(1);
    expect(apiFetch).not.toHaveBeenCalled();
  });

  it("explains a stale screen and keeps the values", async () => {
    apiFetch.mockRejectedValueOnce(problem(409, "version_conflict"));
    const state = await saveFollowUpSettings(0, previous, form(GOOD));
    expect(state.error?.message).toMatch(/Reload/);
    expect(state.values.monthly_cap).toBe("3");
  });

  it("throws for a tampered version", async () => {
    await expect(
      saveFollowUpSettings(-1, previous, form(GOOD)),
    ).rejects.toThrow("invalid version");
    await expect(
      saveFollowUpSettings(1.5, previous, form(GOOD)),
    ).rejects.toThrow("invalid version");
  });
});

describe("the settings form", () => {
  const templates = [
    { id: TEMPLATE, name: "Quick check-in" },
    { id: "44444444-4444-4444-8444-444444444444", name: "Other" },
  ];

  it("starts from the saved settings", () => {
    render(
      <FollowUpSettingsForm
        settings={{
          ...SETTINGS,
          enabled: true,
          template_id: TEMPLATE,
          daily_cap: 40,
        }}
        templates={templates}
        initialState={initialFormState}
        action={vi.fn()}
      />,
    );
    expect(screen.getByLabelText(/Make follow-up drafts/)).toBeChecked();
    expect(screen.getByLabelText("E-mail template")).toHaveValue(TEMPLATE);
    expect(screen.getByLabelText(/Drafts per day/)).toHaveValue("40");
  });

  it("keeps the typed values and shows the error after a refused save", async () => {
    const action = vi.fn().mockResolvedValue({
      attempt: 1,
      values: { ...GOOD, daily_cap: "500", enabled: "on" },
      fieldErrors: { daily_cap: "Enter a whole number from 1 to 100." },
      error: null,
    });
    render(
      <FollowUpSettingsForm
        settings={SETTINGS}
        templates={templates}
        initialState={initialFormState}
        action={action}
      />,
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Save settings" }),
    );
    expect(await screen.findByText(/from 1 to 100/)).toBeInTheDocument();
    expect(screen.getByLabelText(/Drafts per day/)).toHaveValue("500");
    expect(screen.getByLabelText(/Make follow-up drafts/)).toBeChecked();
    expect(screen.getByLabelText("E-mail template")).toHaveValue(TEMPLATE);
  });
});

// --- permissions and menu -------------------------------------------------------------------

describe("permissions", () => {
  it("only the follow_up:manage permission shows the menu entry", () => {
    const labels = (m: Me) => navigationFor(m).map((i) => i.label);
    expect(labels(me(["follow_up:manage"]))).toContain("Follow-ups");
    expect(labels(me(["agent_action:approve"]))).not.toContain("Follow-ups");
    expect(canManageFollowUps(me(["follow_up:manage"]))).toBe(true);
    expect(canManageFollowUps(me(["agent_action:approve"]))).toBe(false);
    expect(PERMISSION_LABELS["follow_up:manage"]).toBeTruthy();
  });

  it("the owner of a lead may decide on a draft; a stranger cannot even with the buttons", () => {
    const agent = me(["agent_action:propose"]);
    expect(canDecideOn(agent, draft())).toBe(true); // the API decides who owns the lead
    expect(canDecideOn(agent, draft({ kind: "lead.set_status" }))).toBe(false);
    expect(canDecideOn(agent, draft({ requested_by_user_id: ME }))).toBe(false);
    expect(canDecideOn(agent, draft({ status: "approved" }))).toBe(false);
  });
});

// --- the card shows what will be sent -------------------------------------------------------

describe("followUpDraft", () => {
  it("reads the subject and text of a follow-up only", () => {
    expect(followUpDraft(draft())).toEqual({
      subject: "Checking in <b>today</b>",
      body: "Hello Asha,\n\nIs Saturday still good?",
    });
    expect(followUpDraft(draft({ kind: "lead.set_status" }))).toBeNull();
    expect(
      followUpDraft(draft({ payload: { subject: 1, body: 2 } })),
    ).toBeNull();
  });
});

describe("the approval card of a follow-up", () => {
  it("shows the full subject and text as plain text, not markup", () => {
    const { container } = render(
      <ApprovalCard action={draft()} people={{}} me={{ user_id: ME }} />,
    );
    const mail = screen.getByRole("group", { name: "The e-mail" });
    expect(
      within(mail).getByText("Checking in <b>today</b>"),
    ).toBeInTheDocument();
    expect(mail.textContent).toContain("Is Saturday still good?");
    expect(container.querySelector("b")).toBeNull();
    expect(mail.textContent).toMatch(/consent and the hourly limit/i);
  });

  it("does not repeat the e-mail as a raw change line", () => {
    render(<ApprovalCard action={draft()} people={{}} me={{ user_id: ME }} />);
    expect(screen.queryByRole("group", { name: "Would change" })).toBeNull();
  });

  it("names the follow-up assistant", () => {
    render(<ApprovalCard action={draft()} people={{}} me={{ user_id: ME }} />);
    expect(screen.getByText(/the follow-up assistant/)).toBeInTheDocument();
  });

  it("a decided draft shows what was sent without the waiting note", () => {
    render(
      <ApprovalCard
        action={draft({ status: "approved" })}
        people={{}}
        me={{ user_id: ME }}
      />,
    );
    expect(
      screen.getByRole("group", { name: "The e-mail" }).textContent,
    ).not.toMatch(/checked again when/);
  });

  it("other proposals keep their change list", () => {
    render(
      <ApprovalCard
        action={draft({
          kind: "lead.set_status",
          payload: { status: "contacted" },
          changes: [{ field: "status", before: "new", after: "contacted" }],
        })}
        people={{}}
        me={{ user_id: ME }}
      />,
    );
    expect(
      screen.getByRole("group", { name: "Would change" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "The e-mail" })).toBeNull();
  });

  it("the lead page list names the subject of a waiting draft", () => {
    render(<RecordProposalsList items={[draft()]} />);
    expect(
      screen.getByText(/Follow-up e-mail: Checking in/),
    ).toBeInTheDocument();
  });

  it("describes the e-mail change as a sentence", () => {
    const text = describeChange(
      { field: "email", before: null, after: { subject: "Hi", body: "x" } },
      () => "",
    );
    expect(text).toBe('E-mail: one e-mail is queued, subject "Hi"');
  });

  it("explains an edit the API refused", () => {
    expect(decisionErrorText("agent_action_edit_refused")).toMatch(/links/);
    expect(decisionErrorText("agent_action_edit_not_allowed")).toMatch(
      /follow-up/,
    );
  });
});

// --- reword before approving ----------------------------------------------------------------

describe("the decision dialog", () => {
  async function openApprove() {
    await userEvent.click(screen.getByRole("button", { name: "Approve" }));
    return screen.getByRole("dialog");
  }

  it("offers the subject and text, prefilled, only for a follow-up", async () => {
    render(
      <ApprovalDecision
        description="Send a follow-up e-mail"
        approve={vi.fn()}
        reject={vi.fn()}
        draft={{ subject: "Hello", body: "Text here" }}
      />,
    );
    const dialog = await openApprove();
    expect(within(dialog).getByLabelText("Subject")).toHaveValue("Hello");
    expect(within(dialog).getByLabelText("Text")).toHaveValue("Text here");
  });

  it("offers no such fields for any other proposal", async () => {
    render(
      <ApprovalDecision
        description="Change the status"
        approve={vi.fn()}
        reject={vi.fn()}
      />,
    );
    const dialog = await openApprove();
    expect(within(dialog).queryByLabelText("Subject")).toBeNull();
    expect(within(dialog).queryByLabelText("Text")).toBeNull();
  });

  it("sends the reworded text with the approval", async () => {
    const approve = vi.fn().mockResolvedValue({
      attempt: 1,
      fieldErrors: {},
      error: null,
    });
    render(
      <ApprovalDecision
        description="Send a follow-up e-mail"
        approve={approve}
        reject={vi.fn()}
        draft={{ subject: "Hello", body: "Text here" }}
      />,
    );
    const dialog = await openApprove();
    const subject = within(dialog).getByLabelText("Subject");
    await userEvent.clear(subject);
    await userEvent.type(subject, "A better subject");
    await userEvent.click(
      within(dialog).getByRole("button", { name: "Approve and run" }),
    );
    const sent = approve.mock.calls[0][1] as FormData;
    expect(sent.get("subject")).toBe("A better subject");
    expect(sent.get("body")).toBe("Text here");
  });
});

describe("the approval Server Actions", () => {
  const previous = { attempt: 0, fieldErrors: {}, error: null };

  it("send the edit with an approval of a follow-up", async () => {
    apiFetch.mockResolvedValueOnce({});
    await expect(
      approveProposal(
        ACTION,
        4,
        previous,
        form({ subject: "New subject", body: "New text", note: "ok" }),
      ),
    ).rejects.toThrow("REDIRECT");
    const [path, init] = apiFetch.mock.calls[0];
    expect(path).toBe(`/approvals/actions/${ACTION}/approve`);
    expect(JSON.parse(init.body)).toEqual({
      version: 4,
      note: "ok",
      edit: { subject: "New subject", body: "New text" },
    });
  });

  it("send no edit for any other approval", async () => {
    apiFetch.mockResolvedValueOnce({});
    await expect(
      approveProposal(ACTION, 4, previous, form({ note: "" })),
    ).rejects.toThrow("REDIRECT");
    expect(JSON.parse(apiFetch.mock.calls[0][1].body).edit).toBeUndefined();
  });

  it("never send an edit with a rejection", async () => {
    apiFetch.mockResolvedValueOnce({});
    await expect(
      rejectProposal(
        ACTION,
        4,
        previous,
        form({ note: "Not now", subject: "x", body: "y" }),
      ),
    ).rejects.toThrow("REDIRECT");
    expect(JSON.parse(apiFetch.mock.calls[0][1].body).edit).toBeUndefined();
  });

  it("explain a refused edit in plain words", async () => {
    apiFetch.mockRejectedValueOnce(problem(422, "agent_action_edit_refused"));
    const state = await approveProposal(
      ACTION,
      4,
      previous,
      form({ subject: "S", body: "https://x.test" }),
    );
    expect(state.error?.message).toMatch(/links/);
  });
});

describe("who asked for a follow-up draft", () => {
  it("is the CRM itself when the requester is not a known person", () => {
    render(<ApprovalCard action={draft()} people={{}} me={{ user_id: ME }} />);
    expect(
      screen.getByText(/Asked by the CRM automatically/),
    ).toBeInTheDocument();
    expect(screen.queryByText(/former colleague/)).toBeNull();
  });

  it("still names a known person, and other proposals keep the old wording", () => {
    render(
      <ApprovalCard
        action={draft()}
        people={{ [OTHER]: "Ravi" }}
        me={{ user_id: ME }}
      />,
    );
    expect(screen.getByText(/Asked by Ravi/)).toBeInTheDocument();
  });

  it("a staff assistant proposal from someone who left is still a former colleague", () => {
    render(
      <ApprovalCard
        action={draft({ kind: "lead.set_status", agent: "staff_assistant" })}
        people={{}}
        me={{ user_id: ME }}
      />,
    );
    expect(screen.getByText(/Asked by a former colleague/)).toBeInTheDocument();
  });
});
