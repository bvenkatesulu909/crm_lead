// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { agentLabel } from "@/components/approval-views";
import { CustomAgentForm } from "@/components/custom-agent-form";
import {
  RetireCustomAgent,
  SwitchCustomAgent,
} from "@/components/custom-agent-controls";
import { CustomAgentTry } from "@/components/custom-agent-try";
import { CustomAgentsSection } from "@/components/custom-agents-section";
import { RunCustomAgentButton } from "@/components/run-custom-agent";
import type {
  CustomAgent,
  CustomAgentMenus,
  CustomAgentRun,
} from "@/lib/api-types";
import {
  agentState,
  customAgentErrorText,
  definitionFromForm,
  definitionToValues,
  initialTrialState,
  isRunnable,
  kindAllowed,
  outcomeText,
  recordPath,
  recordTypeOf,
  splitList,
} from "@/lib/custom-agents";
import { initialFormState } from "@/lib/form-state";

const apiFetch = vi.fn();
vi.mock("@/lib/server/api", () => ({
  apiFetch: (...a: unknown[]) => apiFetch(...a),
}));
vi.mock("next/navigation", () => ({
  redirect: (to: string) => {
    throw new Error(`REDIRECT:${to}`);
  },
}));

const ID = "11111111-1111-4111-8111-111111111111";
const RECORD = "22222222-2222-4222-8222-222222222222";

const MENUS: CustomAgentMenus = {
  read_sets: [
    { key: "lead", description: "The lead's own fields.", record_type: "lead" },
    {
      key: "lead_activity",
      description: "The lead's recent timeline.",
      record_type: "lead",
    },
    {
      key: "account",
      description: "The account's own fields.",
      record_type: "account",
    },
    { key: "deal", description: "The deal's own fields.", record_type: "deal" },
  ],
  suggestion_kinds: [
    {
      key: "lead.set_status",
      description: "Suggest a new status for a lead.",
      record_type: null,
    },
    {
      key: "activity.create_task",
      description: "Suggest a follow-up task.",
      record_type: null,
    },
  ],
  max_read_sets: 3,
  max_suggestion_kinds: 2,
  max_agents: 10,
  name_max: 60,
  purpose_max: 200,
  instruction_max: 4000,
};

function agent(changes: Partial<CustomAgent> = {}): CustomAgent {
  return {
    id: ID,
    agent_key: "custom_abcdefghijkl",
    name: "Quiet lead helper",
    purpose: "Suggest a follow-up task for quiet leads.",
    record_type: "lead",
    read_sets: ["lead"],
    suggestion_kinds: ["activity.create_task"],
    instruction: "Read the lead.",
    current_version: 1,
    version: 1,
    enabled: true,
    tried: true,
    created_at: "2026-11-16T10:00:00Z",
    updated_at: "2026-11-16T10:00:00Z",
    ...changes,
  };
}

function problem(message: string, code = "x") {
  return {
    title: "x",
    status: 422,
    message,
    code,
    fieldErrors: {},
    requestId: null,
  };
}

describe("plain words", () => {
  it("explains the codes a person can meet and keeps the API's words for the rest", () => {
    expect(customAgentErrorText("agent_unavailable", "x")).toContain(
      "switched off",
    );
    expect(customAgentErrorText("custom_agent_needs_trial", "x")).toContain(
      "dry run",
    );
    expect(
      customAgentErrorText("custom_agent_rate_limited", "Try later."),
    ).toBe("Try later.");
    expect(customAgentErrorText(undefined, "Plain.")).toBe("Plain.");
  });

  it("says what a run came to, and never claims a change was made", () => {
    expect(outcomeText("proposed")).toContain("Nothing changes until");
    expect(outcomeText("no_proposal")).toContain("nothing to suggest");
    expect(outcomeText("blocked")).toContain("safety check");
    expect(outcomeText("something-new")).toContain("nothing to suggest");
  });

  it("describes what an agent still needs", () => {
    expect(agentState({ enabled: true, tried: true }).tone).toBe("good");
    expect(agentState({ enabled: true, tried: false }).label).toContain(
      "needs a dry run",
    );
    expect(agentState({ enabled: false, tried: true }).label).toBe(
      "Ready to switch on",
    );
    expect(agentState({ enabled: false, tried: false }).tone).toBe("off");
  });

  it("offers a run button only for an agent that is on and tried", () => {
    expect(isRunnable({ enabled: true, tried: true })).toBe(true);
    expect(isRunnable({ enabled: true, tried: false })).toBe(false);
    expect(isRunnable({ enabled: false, tried: true })).toBe(false);
  });
});

describe("the menus", () => {
  it("finds the one kind of record the chosen read sets are about", () => {
    expect(recordTypeOf(["lead", "lead_activity"], MENUS.read_sets)).toBe(
      "lead",
    );
    expect(recordTypeOf(["account"], MENUS.read_sets)).toBe("account");
    expect(recordTypeOf(["lead", "deal"], MENUS.read_sets)).toBeNull();
    expect(recordTypeOf([], MENUS.read_sets)).toBeNull();
    expect(recordTypeOf(["unknown"], MENUS.read_sets)).toBeNull();
  });

  it("allows a lead status only for an agent that reads a lead", () => {
    expect(kindAllowed("lead.set_status", "lead")).toBe(true);
    expect(kindAllowed("lead.set_status", null)).toBe(true);
    expect(kindAllowed("lead.set_status", "account")).toBe(false);
    expect(kindAllowed("activity.create_task", "deal")).toBe(true);
  });

  it("sends a person only to a record page for a real id", () => {
    expect(recordPath("lead", RECORD)).toBe(`/leads/${RECORD}`);
    expect(recordPath("account", RECORD)).toBe(`/accounts/${RECORD}`);
    expect(recordPath("deal", RECORD)).toBe(`/opportunities/${RECORD}`);
    expect(() => recordPath("lead", "../../admin")).toThrow();
  });
});

describe("the definition form values", () => {
  it("reads what the form sent, and keeps it as text", () => {
    const form = new FormData();
    form.set("name", "N");
    form.set("purpose", "P");
    form.set("instruction", "I");
    form.append("read_sets", "lead");
    form.append("read_sets", "lead_activity");
    form.append("suggestion_kinds", "activity.create_task");
    const values = definitionFromForm(form);
    expect(values.read_sets).toEqual(["lead", "lead_activity"]);
    const kept = definitionToValues(values);
    expect(kept.read_sets).toBe("lead,lead_activity");
    expect(splitList(kept.read_sets)).toEqual(["lead", "lead_activity"]);
    expect(splitList("")).toEqual([]);
    expect(splitList(undefined)).toEqual([]);
  });
});

describe("the definition form", () => {
  const initial = {
    name: "",
    purpose: "",
    instruction: "",
    read_sets: [],
    suggestion_kinds: [],
  };

  it("lists the menus, grouped by kind of record, with the limits", () => {
    render(
      <CustomAgentForm
        menus={MENUS}
        initial={initial}
        initialState={initialFormState}
        action={vi.fn()}
        submitLabel="Create the agent"
      />,
    );
    expect(screen.getByText("About a lead")).toBeInTheDocument();
    expect(screen.getByText("About an account")).toBeInTheDocument();
    expect(screen.getByLabelText("The lead's own fields.")).toBeInTheDocument();
    expect(
      screen.getByLabelText(/Suggest a follow-up task/),
    ).toBeInTheDocument();
    expect(screen.getByText(/choose up to 3/)).toBeInTheDocument();
    expect(
      screen.getByText(/never approve, delete, convert/),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Create the agent" }),
    ).toBeInTheDocument();
  });

  it("names the kind of record and blocks a lead status for an account agent", () => {
    render(
      <CustomAgentForm
        menus={MENUS}
        initial={initial}
        initialState={initialFormState}
        action={vi.fn()}
        submitLabel="Create"
      />,
    );
    const status = screen.getByLabelText(/Suggest a new status for a lead/);
    expect(status).not.toBeDisabled();
    fireEvent.click(screen.getByLabelText("The account's own fields."));
    expect(screen.getByText(/works on an account/)).toBeInTheDocument();
    expect(status).toBeDisabled();
    expect(
      screen.getByText(/needs an agent that reads a lead/),
    ).toBeInTheDocument();
  });

  it("sends what was typed and chosen, and nothing else", async () => {
    const sent: FormData[] = [];
    const action = vi.fn(
      async (state: typeof initialFormState, form: FormData) => {
        sent.push(form);
        return { ...state, attempt: state.attempt + 1 };
      },
    );
    render(
      <CustomAgentForm
        menus={MENUS}
        initial={initial}
        initialState={initialFormState}
        action={action}
        submitLabel="Create"
      />,
    );
    fireEvent.change(screen.getByLabelText("Name"), {
      target: { value: "Quiet lead helper" },
    });
    fireEvent.change(screen.getByLabelText("What it is for"), {
      target: { value: "Chase quiet leads." },
    });
    fireEvent.change(screen.getByLabelText("Instruction"), {
      target: { value: "Read the lead." },
    });
    fireEvent.click(screen.getByLabelText("The lead's own fields."));
    fireEvent.click(screen.getByLabelText(/Suggest a follow-up task/));
    fireEvent.click(screen.getByRole("button", { name: "Create" }));
    await waitFor(() => expect(action).toHaveBeenCalledTimes(1));
    const form = sent[0];
    expect([...form.keys()].sort()).toEqual(
      [
        "instruction",
        "name",
        "purpose",
        "read_sets",
        "suggestion_kinds",
      ].sort(),
    );
    expect(form.getAll("read_sets")).toEqual(["lead"]);
    expect(form.getAll("suggestion_kinds")).toEqual(["activity.create_task"]);
  });

  it("keeps what was typed and chosen when the server refuses, and shows its words", async () => {
    const action = vi.fn(async (state: typeof initialFormState) => ({
      ...state,
      attempt: state.attempt + 1,
      fieldErrors: { name: "Another custom agent already has this name." },
      error: problem("Another custom agent already has this name."),
    }));
    render(
      <CustomAgentForm
        menus={MENUS}
        initial={initial}
        initialState={initialFormState}
        action={action}
        submitLabel="Create"
      />,
    );
    fireEvent.change(screen.getByLabelText("Name"), {
      target: { value: "Typed name" },
    });
    fireEvent.change(screen.getByLabelText("Instruction"), {
      target: { value: "Typed instruction" },
    });
    fireEvent.click(screen.getByLabelText("The account's own fields."));
    fireEvent.click(screen.getByRole("button", { name: "Create" }));
    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent(
        "already has this name",
      ),
    );
    expect(screen.getByLabelText("Name")).toHaveValue("Typed name");
    expect(screen.getByLabelText("Instruction")).toHaveValue(
      "Typed instruction",
    );
    expect(screen.getByLabelText("The account's own fields.")).toBeChecked();
  });
});

describe("the dry run", () => {
  const choices = [
    { id: RECORD, label: "Asha Rao - Acme" },
    { id: ID, label: "Ravi Kumar" },
  ];

  it("shows what the agent would do as plain text, and says nothing changed", async () => {
    const action = vi.fn(async () => ({
      attempt: 1,
      fieldErrors: {},
      error: null,
      values: { record_id: RECORD },
      trial: {
        run_id: ID,
        version_no: 2,
        action: "create_task",
        reason: "<img src=x onerror=alert(1)> No contact for weeks.",
        would_propose: "Create a follow-up task: Call the buyer",
        sets_shown: ["lead", "lead_activity"],
      },
    }));
    const { container } = render(
      <CustomAgentTry
        recordLabel="Lead"
        choices={choices}
        initialState={initialTrialState}
        action={action}
      />,
    );
    fireEvent.change(screen.getByLabelText("Lead"), {
      target: { value: RECORD },
    });
    fireEvent.click(screen.getByRole("button", { name: /Try it/ }));
    await waitFor(() =>
      expect(screen.getByRole("status")).toHaveTextContent(
        "Version 2 would: Create a follow-up task",
      ),
    );
    expect(screen.getByRole("status")).toHaveTextContent("Call the buyer");
    expect(screen.getByRole("status")).toHaveTextContent(
      "Nothing was proposed",
    );
    // What a model wrote is text, never markup.
    expect(container.querySelector("img")).toBeNull();
    expect(screen.getByRole("status")).toHaveTextContent("<img src=x");
  });

  it("shows the server's words when the dry run did not work", async () => {
    const action = vi.fn(async () => ({
      attempt: 1,
      fieldErrors: {},
      error: problem(
        "The agent did not give a usable answer. Please try again.",
      ),
      values: {},
      trial: null,
    }));
    render(
      <CustomAgentTry
        recordLabel="Deal"
        choices={choices}
        initialState={initialTrialState}
        action={action}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /Try it/ }));
    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent("usable answer"),
    );
  });
});

describe("switching on and retiring", () => {
  it("cannot switch on before a dry run, and says why", () => {
    render(
      <SwitchCustomAgent
        enabled={false}
        tried={false}
        onAction={vi.fn()}
        offAction={vi.fn()}
      />,
    );
    expect(screen.getByRole("button", { name: "Switch on" })).toBeDisabled();
    expect(
      screen.getByText(/Run a dry run of this version first/),
    ).toBeInTheDocument();
  });

  it("switches on after a dry run and off when it is on", async () => {
    const onAction = vi.fn(async () => ({
      attempt: 0,
      fieldErrors: {},
      error: null,
    }));
    const offAction = vi.fn(async () => ({
      attempt: 0,
      fieldErrors: {},
      error: null,
    }));
    const { rerender } = render(
      <SwitchCustomAgent
        enabled={false}
        tried
        onAction={onAction}
        offAction={offAction}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Switch on" }));
    await waitFor(() => expect(onAction).toHaveBeenCalled());
    expect(offAction).not.toHaveBeenCalled();
    rerender(
      <SwitchCustomAgent
        enabled
        tried
        onAction={onAction}
        offAction={offAction}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Switch off" }));
    await waitFor(() => expect(offAction).toHaveBeenCalled());
  });

  it("shows the registry's refusal", async () => {
    const onAction = vi.fn(async () => ({
      attempt: 1,
      fieldErrors: {},
      error: problem("Run a dry run of the current version first."),
    }));
    render(
      <SwitchCustomAgent
        enabled={false}
        tried
        onAction={onAction}
        offAction={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Switch on" }));
    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent("dry run"),
    );
  });

  it("asks before retiring and does nothing when the answer is no", async () => {
    const action = vi.fn(async () => ({
      attempt: 0,
      fieldErrors: {},
      error: null,
    }));
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    render(<RetireCustomAgent action={action} />);
    fireEvent.click(screen.getByRole("button", { name: "Retire this agent" }));
    expect(confirm).toHaveBeenCalledWith(
      expect.stringContaining("Retire this agent?"),
    );
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(action).not.toHaveBeenCalled();
    confirm.mockReturnValue(true);
    fireEvent.click(screen.getByRole("button", { name: "Retire this agent" }));
    await waitFor(() => expect(action).toHaveBeenCalled());
    confirm.mockRestore();
  });
});

describe("the run button on a record", () => {
  const run = (changes: Partial<CustomAgentRun> = {}): CustomAgentRun => ({
    id: ID,
    version_no: 1,
    mode: "run",
    record_type: "lead",
    record_id: RECORD,
    action: "create_task",
    outcome: "proposed",
    proposal_id: ID,
    proposal_link: `/approvals/${ID}`,
    blocked_message: null,
    user_id: ID,
    created_at: "2026-11-16T10:00:00Z",
    ...changes,
  });

  it("links to the suggestion and says nothing changes until it is approved", async () => {
    const action = vi.fn(async () => ({
      attempt: 1,
      error: null,
      result: run(),
    }));
    render(
      <RunCustomAgentButton
        name="Quiet lead helper"
        purpose="Chase quiet leads."
        action={action}
      />,
    );
    expect(screen.getByText("Chase quiet leads.")).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "Run Quiet lead helper" }),
    );
    await waitFor(() =>
      expect(screen.getByRole("status")).toHaveTextContent(
        "Nothing changes until",
      ),
    );
    expect(
      screen.getByRole("link", { name: "Open the suggestion" }),
    ).toHaveAttribute("href", `/approvals/${ID}`);
  });

  it("says when the safety check stopped the suggestion and links nowhere", async () => {
    const action = vi.fn(async () => ({
      attempt: 1,
      error: null,
      result: run({
        outcome: "blocked",
        proposal_id: null,
        proposal_link: null,
        blocked_message: "The reason contained a link.",
      }),
    }));
    render(<RunCustomAgentButton name="A" purpose="P" action={action} />);
    fireEvent.click(screen.getByRole("button", { name: "Run A" }));
    await waitFor(() =>
      expect(screen.getByRole("status")).toHaveTextContent("safety check"),
    );
    expect(screen.getByRole("status")).toHaveTextContent("contained a link");
    expect(screen.queryByRole("link")).toBeNull();
  });

  it("shows the server's words when the agent is switched off", async () => {
    const action = vi.fn(async () => ({
      attempt: 1,
      error: problem("This agent is switched off.", "agent_unavailable"),
      result: null,
    }));
    render(<RunCustomAgentButton name="A" purpose="P" action={action} />);
    fireEvent.click(screen.getByRole("button", { name: "Run A" }));
    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent("switched off"),
    );
  });
});

describe("the card on a record's page", () => {
  const page = (items: CustomAgent[]) => ({ items, max_agents: 10 });

  it("shows only agents for this kind of record that are on and tried", async () => {
    apiFetch.mockResolvedValue(
      page([
        agent({ id: "a", name: "Runs on leads" }),
        agent({ id: "b", name: "Account agent", record_type: "account" }),
        agent({ id: "c", name: "Switched off", enabled: false }),
        agent({ id: "d", name: "Not tried", tried: false }),
      ]),
    );
    const element = await CustomAgentsSection({
      me: { permissions: ["custom_agent:run"] },
      recordType: "lead",
      recordId: RECORD,
    });
    render(element);
    expect(
      screen.getByRole("heading", { name: "Custom agents" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Run Runs on leads" }),
    ).toBeInTheDocument();
    for (const hidden of ["Account agent", "Switched off", "Not tried"])
      expect(screen.queryByText(new RegExp(hidden))).toBeNull();
  });

  it("shows nothing without the right, without a matching agent, or when the list fails", async () => {
    apiFetch.mockResolvedValue(page([agent()]));
    expect(
      await CustomAgentsSection({
        me: { permissions: ["lead:read:all"] },
        recordType: "lead",
        recordId: RECORD,
      }),
    ).toBeNull();
    expect(
      await CustomAgentsSection({
        me: { permissions: ["custom_agent:run"] },
        recordType: "deal",
        recordId: RECORD,
      }),
    ).toBeNull();
    apiFetch.mockRejectedValue(new Error("down"));
    expect(
      await CustomAgentsSection({
        me: { permissions: ["custom_agent:run"] },
        recordType: "lead",
        recordId: RECORD,
      }),
    ).toBeNull();
  });
});

describe("who made a proposal", () => {
  it("names a custom agent, also after it was retired, and never invents a name", () => {
    expect(
      agentLabel({
        agent: "custom_agent",
        custom_agent_name: "Quiet lead helper",
      }),
    ).toBe('the custom agent "Quiet lead helper"');
    expect(agentLabel({ agent: "custom_agent", custom_agent_name: null })).toBe(
      "a custom agent",
    );
    expect(agentLabel({ agent: "qualifier", custom_agent_name: null })).toBe(
      "the Qualifier",
    );
    expect(agentLabel({ agent: "brand_new", custom_agent_name: null })).toBe(
      "an AI feature",
    );
  });
});
