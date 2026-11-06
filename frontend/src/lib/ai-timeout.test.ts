import { beforeEach, describe, expect, it, vi } from "vitest";

import { askStaffAssistant } from "@/app/(app)/assistant/actions";
import { initialStaffAssistantState } from "@/app/(app)/assistant/state";
import { askLeadAgent } from "@/app/(app)/lead-agent/actions";
import { qualifyLead, tryProcedure } from "@/app/(app)/qualifier/actions";
import { sendMessage } from "@/app/portal/assistant/actions";
import { initialDialogState } from "@/lib/dialog-state";
import { initialTrialState } from "@/lib/qualifier-state";

/**
 * Found on the first real server (2026-11-06): a free OpenRouter model answered the staff
 * assistant in 14.6 s, but the web app gave up after its default 10 s and showed "temporarily
 * unavailable" although the API had answered. Every call that waits for an AI model must give
 * its own, longer deadline (as the knowledge answers already did).
 */

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

function form(values: Record<string, string>): FormData {
  const data = new FormData();
  for (const [k, v] of Object.entries(values)) data.set(k, v);
  return data;
}

function waitsLonger(path: string) {
  const call = apiFetch.mock.calls.find((c) => c[0] === path);
  expect(call, path).toBeDefined();
  expect(call![1].signal, `${path} needs its own deadline`).toBeInstanceOf(
    AbortSignal,
  );
}

describe("calls that wait for an AI model have a longer deadline", () => {
  beforeEach(() => {
    apiFetch.mockReset();
    apiFetch.mockResolvedValue({
      answer: "ok",
      links: [],
      outcome: "proposed",
      id: "22222222-2222-4222-8222-222222222222",
      verdict: null,
    });
  });

  it("the staff assistant", async () => {
    await askStaffAssistant(
      initialStaffAssistantState,
      form({ question: "show me 10 leads" }),
    );
    waitsLonger("/assistant/ask");
  });

  it("the customer portal assistant", async () => {
    await sendMessage(
      null,
      { attempt: 0, values: {}, fieldErrors: {}, error: null },
      form({ text: "where is my order?" }),
    ).catch(() => undefined); // redirects on success
    waitsLonger("/portal/assistant/messages");
  });

  it("the Qualifier and its dry run", async () => {
    await qualifyLead(LEAD, initialDialogState).catch(() => undefined);
    waitsLonger("/qualifier/assessments");
    await tryProcedure(initialTrialState, form({ lead_id: LEAD }));
    waitsLonger("/qualifier/procedure/try");
  });

  it("the lead agent", async () => {
    await askLeadAgent(LEAD, initialDialogState).catch(() => undefined);
    waitsLonger("/lead-agent/runs");
  });
});
