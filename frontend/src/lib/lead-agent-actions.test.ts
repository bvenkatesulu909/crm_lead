import { describe, expect, it, vi } from "vitest";

import { askLeadAgent } from "@/app/(app)/lead-agent/actions";
import { ApiError } from "@/lib/api-error";
import { initialDialogState } from "@/lib/dialog-state";

const apiFetch = vi.fn();
vi.mock("@/lib/server/api", () => ({
  apiFetch: (...a: unknown[]) => apiFetch(...a),
}));
vi.mock("next/navigation", () => ({
  redirect: (to: string) => {
    throw new Error(`REDIRECT:${to}`);
  },
}));

const LEAD = "11111111-1111-4111-8111-111111111111";

function problem(status: number, code: string, detail = "Server words") {
  return new ApiError(status, {
    title: "x",
    status,
    detail,
    code,
    request_id: "req-1",
  });
}

describe("askLeadAgent", () => {
  it("sends only the lead and goes back to the lead's card with the outcome", async () => {
    apiFetch.mockResolvedValue({ outcome: "proposed" });
    await expect(askLeadAgent(LEAD, initialDialogState)).rejects.toThrow(
      `REDIRECT:/leads/${LEAD}?done=lead-agent-proposed#lead-agent`,
    );
    expect(apiFetch).toHaveBeenCalledWith(
      "/lead-agent/runs",
      expect.objectContaining({ method: "POST" }),
    );
    expect(JSON.parse(apiFetch.mock.calls[0][1].body as string)).toEqual({
      lead_id: LEAD,
    });
  });

  it("says so when the agent suggests nothing", async () => {
    apiFetch.mockResolvedValue({ outcome: "no_suggestion" });
    await expect(askLeadAgent(LEAD, initialDialogState)).rejects.toThrow(
      "?done=lead-agent-nothing",
    );
  });

  it("refuses a tampered lead id before calling the API", async () => {
    apiFetch.mockClear();
    await expect(
      askLeadAgent("../../admin", initialDialogState),
    ).rejects.toThrow("invalid lead");
    expect(apiFetch).not.toHaveBeenCalled();
  });

  it("turns the API's code into plain words and stays on the page", async () => {
    apiFetch.mockImplementation(async () => {
      throw problem(503, "agent_unavailable");
    });
    const state = await askLeadAgent(LEAD, initialDialogState);
    expect(state.attempt).toBe(1);
    expect(state.error?.message).toContain("switched off");
  });

  it("keeps the API's own words for a limit", async () => {
    apiFetch.mockImplementation(async () => {
      throw problem(429, "lead_agent_rate_limited", "Try again in an hour.");
    });
    const state = await askLeadAgent(LEAD, initialDialogState);
    expect(state.error?.message).toBe("Try again in an hour.");
  });
});
