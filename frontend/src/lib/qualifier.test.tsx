import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ProcedureEditor, TrialResult } from "@/components/procedure-editor";
import { QualifyButton } from "@/components/qualify-button";
import {
  AssessmentHistory,
  type HistoryItem,
} from "@/components/qualifier-views";
import { ApprovalCard } from "@/components/approval-views";
import type { AgentAction, QualifierTrial } from "@/lib/api-types";
import { initialDialogState } from "@/lib/dialog-state";
import {
  canManageQualifier,
  canReadQualifier,
  canRunQualifier,
  PERMISSION_LABELS,
} from "@/lib/permissions";
import {
  checkProcedureForm,
  decisionLabel,
  leadPath,
  matchedText,
  outcomeText,
  parseSteps,
  qualifierErrorText,
  stepsToText,
} from "@/lib/qualifier";

const LEAD = "11111111-1111-4111-8111-111111111111";

function item(changes: Partial<HistoryItem> = {}): HistoryItem {
  return {
    id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    decision: "qualify",
    matched_steps: [1, 2],
    reasons: ["Phone present and budget high enough."],
    missing: [],
    outcome: "proposed",
    procedure_version: 3,
    proposal_link: "/approvals/bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
    created_at: "2026-11-01T10:00:00Z",
    ...changes,
  };
}

// --- plain words ------------------------------------------------------------------------------------

describe("words", () => {
  it("names every decision and outcome in plain words", () => {
    expect(decisionLabel("qualify")).toBe("Qualify the lead");
    expect(decisionLabel("contact_first")).toBe("Call the lead first");
    expect(decisionLabel("some_new_one")).toBe("some new one");
    expect(outcomeText("proposed")).toContain("waiting for approval");
    expect(outcomeText("blocked")).toContain("nothing was created");
  });

  it("says which steps matched", () => {
    expect(matchedText([])).toBe("No step matched");
    expect(matchedText([2])).toBe("Step 2 matched");
    expect(matchedText([1, 3])).toBe("Steps 1 and 3 matched");
    expect(matchedText([1, 2, 4])).toBe("Steps 1, 2 and 4 matched");
  });

  it("turns the API's codes into plain words and keeps its own text otherwise", () => {
    expect(qualifierErrorText("agent_unavailable", "x")).toContain(
      "switched off",
    );
    expect(
      qualifierErrorText("no_active_qualification_procedure", "x"),
    ).toContain("Ask an administrator");
    expect(qualifierErrorText("qualifier_rate_limited", "Try later")).toBe(
      "Try later",
    );
    expect(qualifierErrorText(undefined, "Plain")).toBe("Plain");
  });
});

// --- reading what an administrator typed ---------------------------------------------------------------

describe("steps", () => {
  it("reads one step per line and drops numbers and blank lines", () => {
    expect(
      parseSteps(
        "1. Has a phone.\n\n2) Budget over 80 lakh\r\n  - not a number\n",
      ),
    ).toEqual(["Has a phone.", "Budget over 80 lakh", "- not a number"]);
    expect(stepsToText(["a b c", "d e f"])).toBe("a b c\nd e f");
  });

  it("checks the form the way the API will", () => {
    expect(checkProcedureForm("Buyers", "The budget is high.")).toEqual({
      ok: true,
      data: { name: "Buyers", steps: ["The budget is high."] },
    });
    const empty = checkProcedureForm("  ", "");
    expect(empty.ok).toBe(false);
    if (!empty.ok)
      expect(Object.keys(empty.fieldErrors).sort()).toEqual(["name", "steps"]);
  });

  it.each([
    ["ab", "too short"],
    ["x".repeat(301), "too long"],
    [
      Array.from({ length: 21 }, (_, i) => `Step number ${i}`).join("\n"),
      "At most 20",
    ],
    [
      Array.from({ length: 15 }, (_, i) => `${"y".repeat(290)}${i}`).join("\n"),
      "at most 4000",
    ],
  ])("refuses steps that are not usable (%#)", (text, message) => {
    const result = checkProcedureForm("Name", text);
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.fieldErrors.steps).toContain(message);
  });

  it("refuses a name that is too long", () => {
    const result = checkProcedureForm("n".repeat(101), "A valid step.");
    expect(result.ok).toBe(false);
  });

  it("builds a lead path and refuses a tampered id", () => {
    expect(leadPath(LEAD)).toBe(`/leads/${LEAD}`);
    expect(() => leadPath("../../admin")).toThrow();
  });
});

// --- permissions (display only) ---------------------------------------------------------------------------

describe("permissions", () => {
  it("separates running, reading and writing", () => {
    const agent = { permissions: ["qualifier:run"] };
    const manager = { permissions: ["qualifier:run", "qualifier:read"] };
    const admin = {
      permissions: ["qualifier:run", "qualifier:read", "qualifier:manage"],
    };
    expect([
      canRunQualifier(agent),
      canReadQualifier(agent),
      canManageQualifier(agent),
    ]).toEqual([true, false, false]);
    expect([
      canRunQualifier(manager),
      canReadQualifier(manager),
      canManageQualifier(manager),
    ]).toEqual([true, true, false]);
    expect([
      canRunQualifier(admin),
      canReadQualifier(admin),
      canManageQualifier(admin),
    ]).toEqual([true, true, true]);
    expect(canRunQualifier({ permissions: [] })).toBe(false);
  });

  it("describes the three permissions on the profile page", () => {
    for (const key of ["qualifier:run", "qualifier:read", "qualifier:manage"])
      expect(PERMISSION_LABELS[key]).toBeTruthy();
  });
});

// --- the lead card ---------------------------------------------------------------------------------------------

describe("assessment history", () => {
  it("says so when a lead was never assessed", () => {
    render(<AssessmentHistory items={[]} />);
    expect(screen.getByText(/has not been assessed yet/i)).toBeInTheDocument();
  });

  it("shows the decision, the steps, the reasons, the version and a link to the proposal", () => {
    render(<AssessmentHistory items={[item()]} />);
    expect(screen.getByText("Qualify the lead")).toBeInTheDocument();
    expect(screen.getByText(/Steps 1 and 2 matched/)).toBeInTheDocument();
    expect(
      screen.getByText("Phone present and budget high enough."),
    ).toBeInTheDocument();
    expect(screen.getByText(/procedure version 3/)).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Open the proposal" }),
    ).toHaveAttribute(
      "href",
      "/approvals/bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
    );
  });

  it("shows missing items and no link when nothing was proposed", () => {
    render(
      <AssessmentHistory
        items={[
          item({
            decision: "need_info",
            outcome: "no_proposal",
            proposal_link: null,
            missing: ["Budget", "Move-in date"],
          }),
        ]}
      />,
    );
    expect(screen.getByText(/Budget; Move-in date/)).toBeInTheDocument();
    expect(screen.queryByRole("link")).toBeNull();
    expect(
      screen.getByText(/Nothing needed to be proposed/),
    ).toBeInTheDocument();
  });

  it("shows model text as plain text, never as markup or a link", () => {
    render(
      <AssessmentHistory
        items={[
          item({
            reasons: ['<img src=x onerror="alert(1)"> https://evil.example'],
            missing: ["<b>bold</b>"],
          }),
        ]}
      />,
    );
    expect(document.querySelector("img")).toBeNull();
    expect(document.querySelector("b")).toBeNull();
    expect(screen.queryByRole("link", { name: /evil/ })).toBeNull();
    expect(screen.getByText(/<img src=x/)).toBeInTheDocument();
  });

  it("lists several assessments, newest first as given", () => {
    render(
      <AssessmentHistory
        items={[
          item({ id: "1", decision: "unqualify" }),
          item({ id: "2", decision: "no_change", matched_steps: [] }),
        ]}
      />,
    );
    const items = screen.getAllByRole("listitem").map((li) => li.textContent);
    expect(items.some((t) => t?.includes("Mark the lead unqualified"))).toBe(
      true,
    );
    expect(items.some((t) => t?.includes("No change suggested"))).toBe(true);
  });
});

describe("Qualify button", () => {
  it("sends nothing but the click and shows the API's words on a failure", async () => {
    const action = vi.fn(async () => ({
      attempt: 1,
      fieldErrors: {},
      error: {
        message: "The Qualifier is switched off for your organisation.",
        code: "agent_unavailable",
        status: 503,
        requestId: "req-1",
        fieldErrors: {},
      },
    }));
    render(<QualifyButton action={action} />);
    fireEvent.click(screen.getByRole("button", { name: "Qualify" }));
    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent("switched off"),
    );
    expect(action).toHaveBeenCalledTimes(1);
    expect(
      screen.getByText(/Nothing changes until a different person approves/),
    ).toBeInTheDocument();
  });
});

// --- the administrator's page ----------------------------------------------------------------------------------

const trial: QualifierTrial = {
  decision: "need_info",
  matched_steps: [1],
  reasons: ["No phone yet."],
  missing: ["Phone number"],
  would_propose: "Create a follow-up task: Ask the buyer for: Phone number",
  procedure_version: null,
};

describe("procedure editor", () => {
  const baseProps = {
    initialName: "Buyers",
    initialSteps: "The lead has a phone number.\nThe budget is high.",
    leads: [{ id: LEAD, label: "Asha Rao - Acme" }],
    saveInitial: { ...initialDialogState, values: {} },
    tryInitial: { ...initialDialogState, trial: null, values: {} },
  };

  it("shows the current text and a lead to try it on", () => {
    render(
      <ProcedureEditor
        {...baseProps}
        saveAction={async (s) => s}
        tryAction={async (s) => s}
      />,
    );
    expect(screen.getByLabelText("Name")).toHaveValue("Buyers");
    expect(screen.getByLabelText("Steps")).toHaveValue(
      "The lead has a phone number.\nThe budget is high.",
    );
    expect(screen.getByText(/2 steps \(at most 20\)/)).toBeInTheDocument();
    expect(
      screen.getByRole("option", { name: "Asha Rao - Acme" }),
    ).toBeInTheDocument();
  });

  it("sends the typed text, and the draft only through a hidden field of the trial form", async () => {
    const saved: Record<string, string>[] = [];
    const tried: Record<string, string>[] = [];
    render(
      <ProcedureEditor
        {...baseProps}
        saveAction={async (s, form) => {
          saved.push(Object.fromEntries(form) as Record<string, string>);
          return s;
        }}
        tryAction={async (s, form) => {
          tried.push(Object.fromEntries(form) as Record<string, string>);
          return { ...s, trial };
        }}
      />,
    );
    fireEvent.change(screen.getByLabelText("Steps"), {
      target: { value: "1. A new first step.\n2. Another one." },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Save as a new version" }),
    );
    await waitFor(() => expect(saved).toHaveLength(1));
    expect(Object.keys(saved[0]).sort()).toEqual(["name", "steps"]);
    expect(saved[0].steps).toContain("A new first step.");

    fireEvent.change(screen.getByLabelText("Lead"), {
      target: { value: LEAD },
    });
    fireEvent.click(screen.getByLabelText(/Use the steps above as a draft/));
    fireEvent.click(screen.getByRole("button", { name: "Try it" }));
    await waitFor(() => expect(tried).toHaveLength(1));
    expect(tried[0].lead_id).toBe(LEAD);
    expect(tried[0].use_draft).toBe("on");
    expect(tried[0].draft_steps).toContain("Another one.");
    expect(Object.keys(tried[0])).not.toContain("tenant_id");
    await waitFor(() =>
      expect(
        screen.getByText(/It would propose: Create a follow-up task/),
      ).toBeInTheDocument(),
    );
  });

  it("keeps what was typed and shows the errors when saving fails", () => {
    render(
      <ProcedureEditor
        {...baseProps}
        saveInitial={{
          attempt: 1,
          fieldErrors: {
            steps: "Step 1 is too short (at least 3 characters).",
          },
          error: null,
          values: { name: "My name", steps: "ab" },
        }}
        saveAction={async (s) => s}
        tryAction={async (s) => s}
      />,
    );
    expect(screen.getByLabelText("Name")).toHaveValue("My name");
    expect(screen.getByLabelText("Steps")).toHaveValue("ab");
    expect(screen.getByText(/Step 1 is too short/)).toBeInTheDocument();
  });

  it("shows a trial error in plain words", () => {
    render(
      <ProcedureEditor
        {...baseProps}
        tryInitial={{
          attempt: 1,
          fieldErrors: {},
          error: {
            message: "The Qualifier is switched off for your organisation.",
            code: "agent_unavailable",
            status: 503,
            requestId: null,
            fieldErrors: {},
          },
          trial: null,
          values: {},
        }}
        saveAction={async (s) => s}
        tryAction={async (s) => s}
      />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("switched off");
  });
});

describe("trial result", () => {
  it("says what would be proposed and which steps were used", () => {
    render(<TrialResult trial={trial} />);
    expect(
      screen.getByText("Ask the buyer for more details"),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/It would propose: Create a follow-up task/),
    ).toBeInTheDocument();
    expect(screen.getByText("Tried with the draft above.")).toBeInTheDocument();
  });

  it("says when nothing would be proposed and names a saved version", () => {
    render(
      <TrialResult
        trial={{
          ...trial,
          decision: "no_change",
          would_propose: null,
          procedure_version: 4,
        }}
      />,
    );
    expect(
      screen.getByText("It would not propose anything."),
    ).toBeInTheDocument();
    expect(screen.getByText("Tried with saved version 4.")).toBeInTheDocument();
  });
});

// --- the approval card ---------------------------------------------------------------------------------------------

describe("approval card", () => {
  it("names the Qualifier as the source of its proposal", () => {
    const action: AgentAction = {
      id: "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
      kind: "lead.set_status",
      description: "Change the lead's status to qualified",
      target_type: "lead",
      target_id: LEAD,
      target_link: `/leads/${LEAD}`,
      target_label: "Asha Rao",
      payload: { status: "qualified" },
      reason: "Qualifier (procedure v1): Phone present.",
      agent: "qualifier",
      via_client: null,
      requested_by_user_id: "22222222-2222-4222-8222-222222222222",
      status: "pending",
      expires_at: "2026-11-08T10:00:00Z",
      decided_by_user_id: null,
      decided_at: null,
      decision_note: null,
      result: null,
      warnings: [],
      changes: [],
      outcome: null,
      created_at: "2026-11-01T10:00:00Z",
      version: 1,
    };
    render(
      <ApprovalCard
        action={action}
        people={{ "22222222-2222-4222-8222-222222222222": "Alex Agent" }}
        me={{ user_id: "11111111-1111-4111-8111-111111111111" }}
      />,
    );
    expect(screen.getByText(/through the Qualifier/)).toBeInTheDocument();
  });
});
