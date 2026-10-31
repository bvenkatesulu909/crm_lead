import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AgentCard } from "@/components/agent-views";
import { AgentSettingsForm } from "@/components/agent-settings-form";
import type { Agent } from "@/lib/api-types";
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

function agent(changes: Partial<Agent> = {}): Agent {
  return {
    key: "web_check",
    title: "Web check",
    description: "Looks up a RERA number or a company on a public registry.",
    owner_role: "tenant_admin",
    uses_model: false,
    enabled: true,
    monthly_token_budget: 2_000_000,
    budget_is_default: true,
    allowed_tools: [],
    all_tools: [],
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

const modelAgent = (changes: Partial<Agent> = {}) =>
  agent({
    key: "staff_assistant",
    title: "Staff assistant",
    uses_model: true,
    all_tools: ["search_leads", "check_rera"],
    allowed_tools: ["search_leads", "check_rera"],
    ...changes,
  });

describe("an agent that uses no model, on the registry page", () => {
  it("counts checks, not tokens, and shows no budget bar", () => {
    render(<AgentCard agent={agent({ calls: 3 })} />);
    expect(screen.getByText(/3 checks this month/)).toBeInTheDocument();
    expect(screen.queryByRole("progressbar")).toBeNull();
    expect(screen.queryByText(/tokens/)).toBeNull();
  });

  it("says one check, not one checks", () => {
    render(<AgentCard agent={agent({ calls: 1 })} />);
    expect(screen.getByText(/1 check this month/)).toBeInTheDocument();
  });

  it("says no checks yet", () => {
    render(<AgentCard agent={agent()} />);
    expect(screen.getByText(/No checks this month/)).toBeInTheDocument();
  });

  it("still says whether it is on or switched off", () => {
    const { rerender } = render(<AgentCard agent={agent()} />);
    expect(screen.getByText("On")).toBeInTheDocument();
    rerender(<AgentCard agent={agent({ enabled: false })} />);
    expect(screen.getByText("Switched off")).toBeInTheDocument();
  });

  it("keeps the token bar for an agent that does use a model", () => {
    render(
      <AgentCard agent={modelAgent({ used_tokens: 500, percent_used: 1 })} />,
    );
    expect(screen.getByRole("progressbar")).toBeInTheDocument();
    expect(
      screen.getByText(/of 2,000,000 tokens used this month/),
    ).toBeInTheDocument();
  });
});

describe("its settings form", () => {
  const noop = async () => initialFormState;

  it("offers only the switch", () => {
    render(
      <AgentSettingsForm
        agent={agent()}
        action={noop}
        initialState={initialFormState}
      />,
    );
    expect(screen.getByLabelText("Switched on")).toBeInTheDocument();
    expect(screen.queryByLabelText("Monthly token budget")).toBeNull();
    expect(screen.queryByText("Tools it may use")).toBeNull();
    expect(
      screen.getByRole("button", { name: "Save settings" }),
    ).toBeInTheDocument();
  });

  it("still offers the budget and the tools for an agent that uses a model", () => {
    render(
      <AgentSettingsForm
        agent={modelAgent()}
        action={noop}
        initialState={initialFormState}
      />,
    );
    expect(screen.getByLabelText("Monthly token budget")).toBeInTheDocument();
    expect(screen.getByText("Tools it may use")).toBeInTheDocument();
  });
});

describe("saving the settings", () => {
  beforeEach(() => apiFetch.mockReset());

  async function save(
    usesModel: boolean,
    fields: Record<string, string | string[]>,
  ) {
    const { updateAgent } =
      await import("@/app/(app)/automation/agents/actions");
    const form = new FormData();
    for (const [name, value] of Object.entries(fields))
      for (const v of Array.isArray(value) ? value : [value])
        form.append(name, v);
    apiFetch.mockResolvedValue({});
    await expect(
      updateAgent("web_check", 2, [], usesModel, initialFormState, form),
    ).rejects.toThrow(/REDIRECT:/);
    return JSON.parse(apiFetch.mock.calls[0][1].body as string);
  }

  it("sends only the switch (and the version) for an agent that uses no model", async () => {
    expect(await save(false, { enabled: "on" })).toEqual({
      version: 2,
      enabled: true,
    });
    apiFetch.mockReset();
    expect(await save(false, {})).toEqual({ version: 2, enabled: false });
  });

  it("sends the budget and the tools for an agent that uses a model", async () => {
    const { updateAgent } =
      await import("@/app/(app)/automation/agents/actions");
    const form = new FormData();
    form.append("enabled", "on");
    form.append("budget", "5000");
    form.append("tools", "search_leads");
    apiFetch.mockResolvedValue({});
    await expect(
      updateAgent(
        "staff_assistant",
        3,
        ["search_leads", "check_rera"],
        true,
        initialFormState,
        form,
      ),
    ).rejects.toThrow(/REDIRECT:/);
    expect(JSON.parse(apiFetch.mock.calls[0][1].body as string)).toEqual({
      version: 3,
      enabled: true,
      monthly_token_budget: 5000,
      allowed_tools: ["search_leads"],
    });
  });
});

describe("the outside-client agent (ADR 0020)", () => {
  const client = (changes: Partial<Agent> = {}) =>
    agent({
      key: "mcp_client",
      title: "AI clients (MCP)",
      enabled: false,
      ...changes,
    });

  it("counts proposals, not checks, and says there is no token budget", () => {
    const { rerender } = render(<AgentCard agent={client()} />);
    expect(screen.getByText(/No proposals this month/)).toBeInTheDocument();
    expect(screen.queryByText(/check/i)).toBeNull();
    rerender(<AgentCard agent={client({ calls: 1 })} />);
    expect(screen.getByText(/1 proposal this month/)).toBeInTheDocument();
    rerender(<AgentCard agent={client({ calls: 3 })} />);
    expect(screen.getByText(/3 proposals this month/)).toBeInTheDocument();
    expect(screen.queryByRole("progressbar")).toBeNull();
  });

  it("shows that it is switched off by default", () => {
    render(<AgentCard agent={client()} />);
    expect(screen.getAllByText(/off/i).length).toBeGreaterThan(0);
  });

  it("keeps counting checks for the web check agent", () => {
    render(<AgentCard agent={agent({ calls: 2 })} />);
    expect(screen.getByText(/2 checks this month/)).toBeInTheDocument();
  });
});
