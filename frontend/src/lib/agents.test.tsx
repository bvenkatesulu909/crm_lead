import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { AgentCard } from "@/components/agent-views";
import { isActive } from "@/components/app-shell";
import { AgentSettingsForm } from "@/components/agent-settings-form";
import type { Agent, Me } from "@/lib/api-types";
import {
  agentErrorText,
  agentState,
  formatTokens,
  parseBudget,
  toggledTools,
} from "@/lib/agents";
import { type FormState, initialFormState } from "@/lib/form-state";
import {
  canManageAgents,
  canReadAgents,
  navigationFor,
} from "@/lib/permissions";

function me(permissions: string[]): Me {
  return {
    user_id: "u1",
    display_name: "Test",
    email: null,
    tenant_id: "t",
    tenant_name: "T",
    user_type: "staff",
    roles: [],
    permissions,
  };
}

const TOOLS = ["get_account", "search_leads", "propose_lead_status"];

function agent(changes: Partial<Agent> = {}): Agent {
  return {
    key: "staff_assistant",
    title: "Staff assistant",
    description: "Answers staff questions about leads.",
    owner_role: "tenant_admin",
    enabled: true,
    monthly_token_budget: 2_000_000,
    budget_is_default: true,
    allowed_tools: TOOLS,
    all_tools: TOOLS,
    month: "2026-10-01",
    input_tokens: 0,
    output_tokens: 0,
    used_tokens: 0,
    calls: 0,
    percent_used: 0,
    version: null,
    ...changes,
  };
}

describe("who sees the page", () => {
  it("tenant admins and sales managers read, only admins change", () => {
    expect(canReadAgents(me(["agent:read"]))).toBe(true);
    expect(canManageAgents(me(["agent:read"]))).toBe(false);
    expect(canManageAgents(me(["agent:read", "agent:manage"]))).toBe(true);
    expect(canReadAgents(me(["lead:read:own"]))).toBe(false);
  });

  it("adds an AI agents entry to the menu only for readers", () => {
    const labels = (p: string[]) => navigationFor(me(p)).map((i) => i.label);
    expect(labels(["agent:read"])).toContain("AI agents");
    expect(labels(["lead:read:own"])).not.toContain("AI agents");
    const entry = navigationFor(me(["agent:read"])).find(
      (i) => i.label === "AI agents",
    );
    expect(entry?.href).toBe("/automation/agents");
  });
});

describe("the menu", () => {
  it("lights up one entry at a time on the agents page", () => {
    expect(isActive("/automation/agents", "/automation/agents")).toBe(true);
    expect(isActive("/automation/agents", "/automation")).toBe(false);
    expect(isActive("/automation/new", "/automation")).toBe(true);
    expect(isActive("/automation", "/automation")).toBe(true);
  });
});

describe("helpers", () => {
  it("names the state in words", () => {
    expect(agentState(agent())).toBe("on");
    expect(agentState(agent({ enabled: false }))).toBe("off");
    expect(agentState(agent({ percent_used: 79 }))).toBe("on");
    expect(agentState(agent({ percent_used: 80 }))).toBe("warning");
    expect(agentState(agent({ percent_used: 100 }))).toBe("limit");
    // off wins over usage
    expect(agentState(agent({ enabled: false, percent_used: 100 }))).toBe(
      "off",
    );
  });

  it("formats token counts", () => {
    expect(formatTokens(2_000_000)).toBe("2,000,000 tokens");
    expect(formatTokens(1)).toBe("1 token");
    expect(formatTokens(0)).toBe("0 tokens");
  });

  it("reads a budget: empty = the default, commas and spaces are fine", () => {
    expect(parseBudget("")).toEqual({ value: null });
    expect(parseBudget("   ")).toEqual({ value: null });
    expect(parseBudget("500000")).toEqual({ value: 500000 });
    expect(parseBudget("1,500,000")).toEqual({ value: 1500000 });
    expect(parseBudget("1 500 000")).toEqual({ value: 1500000 });
  });

  it.each(["0", "-5", "1.5", "abc", "10000000001", "2m"])(
    "refuses the budget %s in plain words",
    (text) => {
      const result = parseBudget(text);
      expect("error" in result && result.error.length > 10).toBe(true);
    },
  );

  it("sends null for the tools when all are allowed, else the sorted list", () => {
    expect(toggledTools(TOOLS, TOOLS)).toBeNull();
    expect(toggledTools(["search_leads"], TOOLS)).toEqual(["search_leads"]);
    expect(toggledTools([], TOOLS)).toEqual([]);
    expect(toggledTools(["search_leads", "get_account"], TOOLS)).toEqual([
      "get_account",
      "search_leads",
    ]);
  });

  it("explains the errors the API can give", () => {
    expect(agentErrorText("version_conflict", "x")).toMatch(/someone else/i);
    expect(agentErrorText("agent_not_found", "x")).toMatch(/doesn't exist/i);
    expect(agentErrorText("invalid_agent_setting", "Bad tool")).toBe(
      "Bad tool",
    );
    expect(agentErrorText(undefined, "Other")).toBe("Other");
  });
});

describe("AgentCard", () => {
  it("shows the agent, its state as a word, the usage and the tool count", () => {
    render(
      <AgentCard
        agent={agent({
          used_tokens: 1_000_000,
          percent_used: 50,
          calls: 12,
          allowed_tools: ["search_leads"],
        })}
      />,
    );
    expect(
      screen.getByRole("heading", { name: "Staff assistant" }),
    ).toBeInTheDocument();
    expect(screen.getByText("On")).toBeInTheDocument();
    expect(
      screen.getByText(/1,000,000 of 2,000,000 tokens/),
    ).toBeInTheDocument();
    expect(screen.getByText(/12 calls/)).toBeInTheDocument();
    expect(screen.getByText(/1 of 3 tools/)).toBeInTheDocument();
    const bar = screen.getByRole("progressbar");
    expect(bar).toHaveAttribute("aria-valuenow", "50");
  });

  it.each([
    [{ enabled: false }, "Switched off"],
    [{ percent_used: 85 }, "Near its limit"],
    [{ percent_used: 100 }, "Limit reached"],
  ] as const)("says %j as %s", (changes, word) => {
    render(<AgentCard agent={agent(changes)} />);
    expect(screen.getByText(word)).toBeInTheDocument();
  });

  it("says so when an agent has no tools at all", () => {
    render(<AgentCard agent={agent({ all_tools: [], allowed_tools: [] })} />);
    expect(screen.getByText(/uses no tools/)).toBeInTheDocument();
    expect(screen.queryByText(/0 of 0/)).toBeNull();
  });

  it("marks a default budget as the default", () => {
    render(<AgentCard agent={agent()} />);
    expect(screen.getByText(/standard limit/i)).toBeInTheDocument();
    render(<AgentCard agent={agent({ budget_is_default: false })} />);
    expect(screen.getAllByText(/standard limit/i)).toHaveLength(1);
  });

  it("caps the bar at 100 % and still shows the real number", () => {
    render(<AgentCard agent={agent({ percent_used: 250, used_tokens: 5 })} />);
    expect(screen.getByRole("progressbar")).toHaveAttribute(
      "aria-valuenow",
      "100",
    );
  });

  it("shows text from the server as plain text, not markup", () => {
    render(
      <AgentCard
        agent={agent({ description: "<img src=x onerror=alert(1)> hi" })}
      />,
    );
    expect(screen.getByText(/<img src=x/)).toBeInTheDocument();
    expect(document.querySelector("img")).toBeNull();
  });

  it("puts the settings form in its slot", () => {
    render(
      <AgentCard agent={agent()}>
        <p>form goes here</p>
      </AgentCard>,
    );
    expect(screen.getByText("form goes here")).toBeInTheDocument();
  });
});

describe("AgentSettingsForm", () => {
  const noop: (
    state: FormState,
    data: FormData,
  ) => Promise<FormState> = async () => initialFormState;

  it("starts with the agent's current settings", () => {
    render(
      <AgentSettingsForm
        agent={agent({
          monthly_token_budget: 500_000,
          budget_is_default: false,
          allowed_tools: ["search_leads"],
        })}
        action={noop}
        initialState={initialFormState}
      />,
    );
    expect(screen.getByLabelText(/switched on/i)).toBeChecked();
    expect(screen.getByLabelText(/monthly token budget/i)).toHaveValue(
      "500000",
    );
    expect(screen.getByLabelText("search_leads")).toBeChecked();
    expect(screen.getByLabelText("get_account")).not.toBeChecked();
    expect(screen.getByLabelText("propose_lead_status")).not.toBeChecked();
  });

  it("leaves the budget empty for the default and shows the default as a hint", () => {
    render(
      <AgentSettingsForm
        agent={agent()}
        action={noop}
        initialState={initialFormState}
      />,
    );
    const box = screen.getByLabelText(/monthly token budget/i);
    expect(box).toHaveValue("");
    expect(box).toHaveAttribute("placeholder", "2,000,000");
  });

  it("explains that a switch applies from the next question", () => {
    render(
      <AgentSettingsForm
        agent={agent()}
        action={noop}
        initialState={initialFormState}
      />,
    );
    expect(screen.getByText(/next question/i)).toBeInTheDocument();
  });

  it("sends what was typed and ticked", async () => {
    const action = vi.fn(noop);
    const user = userEvent.setup();
    render(
      <AgentSettingsForm
        agent={agent()}
        action={action}
        initialState={initialFormState}
      />,
    );
    await user.click(screen.getByLabelText(/switched on/i));
    await user.type(screen.getByLabelText(/monthly token budget/i), "1,000");
    await user.click(screen.getByLabelText("propose_lead_status"));
    await user.click(screen.getByRole("button", { name: /save/i }));
    await waitFor(() => expect(action).toHaveBeenCalled());
    const data = action.mock.calls[0][1];
    expect(data.get("enabled")).toBeNull(); // unticked: switched off
    expect(data.get("budget")).toBe("1,000");
    expect(data.getAll("tools")).toEqual(["get_account", "search_leads"]);
  });

  it("shows the API's problem and the field errors, and keeps what was typed", () => {
    render(
      <AgentSettingsForm
        agent={agent()}
        action={noop}
        initialState={{
          attempt: 1,
          values: { budget: "abc" },
          fieldErrors: { budget: "Use whole numbers." },
          error: {
            status: 422,
            message: "The settings could not be saved.",
            code: "invalid_agent_setting",
            requestId: "r1",
            fieldErrors: {},
          },
        }}
      />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent(
      "The settings could not be saved.",
    );
    expect(screen.getByText("Use whole numbers.")).toBeInTheDocument();
    expect(screen.getByLabelText(/monthly token budget/i)).toHaveValue("abc");
  });

  it("is read-only for people who may not change it", () => {
    render(<AgentCard agent={agent()} />);
    expect(screen.queryByRole("button", { name: /save/i })).toBeNull();
    expect(within(document.body).queryAllByRole("checkbox")).toHaveLength(0);
  });
});
