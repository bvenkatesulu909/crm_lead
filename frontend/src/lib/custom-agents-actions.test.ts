import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  archiveCustomAgent,
  createCustomAgent,
  runCustomAgent,
  switchCustomAgent,
  tryCustomAgent,
  updateCustomAgent,
} from "@/app/(app)/custom-agents/actions";
import { ApiError } from "@/lib/api-error";
import { initialRunState, initialTrialState } from "@/lib/custom-agents";
import { initialDialogState } from "@/lib/dialog-state";
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
const KEY = "custom_abcdefghijkl";

function problem(status: number, code: string, detail = "Server words") {
  return new ApiError(status, {
    title: "x",
    status,
    detail,
    code,
    request_id: "req-1",
  });
}

function form(values: Record<string, string | string[]>): FormData {
  const data = new FormData();
  for (const [key, value] of Object.entries(values))
    for (const item of Array.isArray(value) ? value : [value])
      data.append(key, item);
  return data;
}

const DEFINITION = {
  name: "Quiet lead helper",
  purpose: "Chase quiet leads.",
  instruction: "Read the lead.",
  read_sets: ["lead"],
  suggestion_kinds: ["activity.create_task"],
};

beforeEach(() => {
  apiFetch.mockReset();
});

describe("createCustomAgent", () => {
  it("sends the definition and goes to the new agent's page", async () => {
    apiFetch.mockResolvedValue({ id: ID });
    await expect(
      createCustomAgent(initialFormState, form(DEFINITION)),
    ).rejects.toThrow(`REDIRECT:/automation/custom-agents/${ID}?done=created`);
    expect(apiFetch).toHaveBeenCalledWith(
      "/custom-agents",
      expect.objectContaining({ method: "POST" }),
    );
    // Only the definition goes: no organisation, person, key, version or switch.
    expect(JSON.parse(apiFetch.mock.calls[0][1].body as string)).toEqual(
      DEFINITION,
    );
  });

  it("keeps what was typed and shows the API's words when it refuses", async () => {
    apiFetch.mockRejectedValue(
      problem(422, "invalid_custom_agent", "Choose 1-3 read sets."),
    );
    const state = await createCustomAgent(
      initialFormState,
      form({ ...DEFINITION, read_sets: [] }),
    );
    expect(state.error?.message).toBe("Choose 1-3 read sets.");
    expect(state.values.name).toBe("Quiet lead helper");
    expect(state.values.instruction).toBe("Read the lead.");
    expect(state.attempt).toBe(1);
  });
});

describe("updateCustomAgent", () => {
  it("sends the version the editor saw and goes back with a note", async () => {
    apiFetch.mockResolvedValue({ id: ID });
    await expect(
      updateCustomAgent(ID, 3, initialFormState, form(DEFINITION)),
    ).rejects.toThrow(`REDIRECT:/automation/custom-agents/${ID}?done=saved`);
    expect(apiFetch).toHaveBeenCalledWith(
      `/custom-agents/${ID}`,
      expect.objectContaining({ method: "PUT" }),
    );
    expect(JSON.parse(apiFetch.mock.calls[0][1].body as string)).toEqual({
      ...DEFINITION,
      version: 3,
    });
  });

  it("explains a stale screen in plain words", async () => {
    apiFetch.mockRejectedValue(problem(409, "version_conflict", "raw"));
    const state = await updateCustomAgent(
      ID,
      1,
      initialFormState,
      form(DEFINITION),
    );
    expect(state.error?.message).toContain("Someone else changed this agent");
  });

  it("refuses a tampered agent id before calling the API", async () => {
    await expect(
      updateCustomAgent("../../admin", 1, initialFormState, form(DEFINITION)),
    ).rejects.toThrow("invalid agent");
    expect(apiFetch).not.toHaveBeenCalled();
  });
});

describe("archiveCustomAgent", () => {
  it("retires and goes to the list", async () => {
    apiFetch.mockResolvedValue(undefined);
    await expect(archiveCustomAgent(ID, initialDialogState)).rejects.toThrow(
      "REDIRECT:/automation/custom-agents?done=archived",
    );
    expect(apiFetch).toHaveBeenCalledWith(
      `/custom-agents/${ID}/archive`,
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("shows an error and stays", async () => {
    apiFetch.mockRejectedValue(problem(404, "custom_agent_not_found"));
    const state = await archiveCustomAgent(ID, initialDialogState);
    expect(state.error?.message).toContain("no longer exists");
  });
});

describe("tryCustomAgent", () => {
  it("asks for a record without calling the API when none was chosen", async () => {
    const state = await tryCustomAgent(
      ID,
      initialTrialState,
      form({ record_id: "" }),
    );
    expect(state.fieldErrors.record_id).toContain("Choose a record");
    expect(apiFetch).not.toHaveBeenCalled();
  });

  it("sends only the record and returns the answer", async () => {
    const trial = {
      run_id: ID,
      version_no: 1,
      action: "none",
      reason: "Nothing.",
      would_propose: null,
      sets_shown: ["lead"],
    };
    apiFetch.mockResolvedValue(trial);
    const state = await tryCustomAgent(
      ID,
      initialTrialState,
      form({ record_id: RECORD, extra: "ignored" }),
    );
    expect(state.trial).toEqual(trial);
    expect(apiFetch).toHaveBeenCalledWith(
      `/custom-agents/${ID}/try`,
      expect.objectContaining({ method: "POST" }),
    );
    expect(JSON.parse(apiFetch.mock.calls[0][1].body as string)).toEqual({
      record_id: RECORD,
    });
  });

  it("shows the API's refusal and keeps the chosen record", async () => {
    apiFetch.mockRejectedValue(problem(404, "custom_agent_record_not_found"));
    const state = await tryCustomAgent(
      ID,
      initialTrialState,
      form({ record_id: RECORD }),
    );
    expect(state.error?.message).toBe("Record not found.");
    expect(state.values.record_id).toBe(RECORD);
    expect(state.trial).toBeNull();
  });
});

describe("switchCustomAgent", () => {
  it("sends the registry version when the agent has settings, and goes back", async () => {
    apiFetch.mockResolvedValue({});
    await expect(
      switchCustomAgent(ID, KEY, 2, true, initialDialogState),
    ).rejects.toThrow(`REDIRECT:/automation/custom-agents/${ID}?done=on`);
    expect(apiFetch).toHaveBeenCalledWith(
      `/agents/${KEY}`,
      expect.objectContaining({ method: "PATCH" }),
    );
    expect(JSON.parse(apiFetch.mock.calls[0][1].body as string)).toEqual({
      version: 2,
      enabled: true,
    });
  });

  it("leaves the version out for a first switch, and switches off", async () => {
    apiFetch.mockResolvedValue({});
    await expect(
      switchCustomAgent(ID, KEY, null, false, initialDialogState),
    ).rejects.toThrow(`?done=off`);
    expect(JSON.parse(apiFetch.mock.calls[0][1].body as string)).toEqual({
      enabled: false,
    });
  });

  it("shows the registry's refusal when no dry run happened", async () => {
    apiFetch.mockRejectedValue(
      problem(422, "invalid_agent_setting", "Run a dry run first."),
    );
    const state = await switchCustomAgent(
      ID,
      KEY,
      null,
      true,
      initialDialogState,
    );
    expect(state.error?.message).toBe("Run a dry run first.");
  });

  it("refuses an agent key that is not a custom agent's, before calling the API", async () => {
    await expect(
      switchCustomAgent(ID, "qualifier", 1, true, initialDialogState),
    ).rejects.toThrow("invalid agent");
    expect(apiFetch).not.toHaveBeenCalled();
  });
});

describe("runCustomAgent", () => {
  it("sends only the record and returns the result", async () => {
    const result = { outcome: "proposed", proposal_link: `/approvals/${ID}` };
    apiFetch.mockResolvedValue(result);
    const state = await runCustomAgent(ID, RECORD, initialRunState);
    expect(state.result).toEqual(result);
    expect(apiFetch).toHaveBeenCalledWith(
      `/custom-agents/${ID}/runs`,
      expect.objectContaining({ method: "POST" }),
    );
    expect(JSON.parse(apiFetch.mock.calls[0][1].body as string)).toEqual({
      record_id: RECORD,
    });
  });

  it("explains an agent that is off, needs a dry run or is over a limit", async () => {
    apiFetch.mockRejectedValue(problem(503, "agent_unavailable"));
    expect(
      (await runCustomAgent(ID, RECORD, initialRunState)).error?.message,
    ).toContain("switched off");
    apiFetch.mockRejectedValue(problem(409, "custom_agent_needs_trial"));
    expect(
      (await runCustomAgent(ID, RECORD, initialRunState)).error?.message,
    ).toContain("dry run");
    apiFetch.mockRejectedValue(
      problem(429, "custom_agent_rate_limited", "Handled a moment ago."),
    );
    expect(
      (await runCustomAgent(ID, RECORD, initialRunState)).error?.message,
    ).toBe("Handled a moment ago.");
  });

  it("refuses tampered ids before calling the API", async () => {
    await expect(
      runCustomAgent("../x", RECORD, initialRunState),
    ).rejects.toThrow("invalid agent");
    await expect(
      runCustomAgent(ID, "not-an-id", initialRunState),
    ).rejects.toThrow("invalid record");
    expect(apiFetch).not.toHaveBeenCalled();
  });
});
