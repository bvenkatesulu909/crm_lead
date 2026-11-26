// @vitest-environment jsdom
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  cancelBatch,
  estimateBatch,
  estimateRetry,
  startBatch,
  startRetry,
} from "@/app/(app)/accounts/batches/actions";
import {
  ResearchBatchBar,
  TickAll,
  TickBox,
  tickedAccounts,
} from "@/components/research-batch-bar";
import {
  BatchConfirm,
  EstimateView,
} from "@/components/research-batch-confirm";
import {
  BatchAutoRefresh,
  BatchItemsTable,
  BatchSummary,
  RetryPanel,
} from "@/components/research-batch-views";
import { ApiError } from "@/lib/api-error";
import { initialDialogState } from "@/lib/dialog-state";
import { canRunResearchBatches } from "@/lib/permissions";
import {
  batchErrorText,
  cleanConfirmed,
  cleanSelection,
  cleanWhich,
  failureText,
  gatheredText,
  progress,
  retryable,
  type Batch,
  type BatchEstimate,
  type BatchItem,
} from "@/lib/research-batches";

const apiFetch = vi.fn();
vi.mock("@/lib/server/api", () => ({
  apiFetch: (...a: unknown[]) => apiFetch(...a),
}));
vi.mock("next/cache", () => ({ revalidatePath: vi.fn() }));
const refresh = vi.fn();
vi.mock("next/navigation", () => ({
  redirect: (to: string) => {
    throw new Error(`REDIRECT:${to}`);
  },
  useRouter: () => ({ refresh }),
}));
const A = "11111111-1111-4111-8111-111111111111";
const B = "22222222-2222-4222-8222-222222222222";
const F = "33333333-3333-4333-8333-333333333333";

// jsdom has no <dialog> methods.
beforeEach(() => {
  apiFetch.mockReset();
  refresh.mockReset();
  HTMLDialogElement.prototype.showModal = function () {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close = function () {
    this.removeAttribute("open");
  };
});

function estimate(changes: Partial<BatchEstimate> = {}): BatchEstimate {
  return {
    accounts: 2,
    not_available: 1,
    archived: 0,
    reused: 0,
    calling_model: 2,
    upper_bound_tokens: 18048,
    typical_tokens: 1000,
    estimated_cost_usd: "0.0300",
    cap_tokens: 18048,
    monthly_tokens_left: 2000000,
    daily_left: 198,
    worst_case_tokens_per_account: 9024,
    ...changes,
  };
}

function batch(changes: Partial<Batch> = {}): Batch {
  return {
    id: F,
    status: "running",
    source: "rows",
    saved_filter_id: null,
    account_count: 4,
    not_available_count: 0,
    archived_count: 0,
    estimated_upper_tokens: 36096,
    estimated_cost_usd: null,
    token_cap: 36096,
    tokens_used: 500,
    research_again: false,
    cancel_requested: false,
    created_by_user_id: "u1",
    mine: true,
    version: 1,
    created_at: "2026-11-26T10:00:00Z",
    finished_at: null,
    counts: { done: 1, queued: 3 },
    ...changes,
  };
}

function item(changes: Partial<BatchItem> = {}): BatchItem {
  return {
    position: 1,
    account_id: A,
    account_name: "Acme",
    status: "done",
    failure_code: null,
    brief_id: B,
    input_tokens: 300,
    output_tokens: 200,
    brief: {
      brief_id: B,
      created_at: "2026-11-26T10:01:00Z",
      sentences: 3,
      dropped: 0,
      gathered: { sales: 2, service: 0, conversations: 1 },
      tokens: 500,
    },
    ...changes,
  };
}

// --- helpers ------------------------------------------------------------------------------------

describe("helpers", () => {
  it("keeps a selection of ticked rows, without duplicates", () => {
    expect(
      cleanSelection({
        source: "rows",
        account_ids: [A, B, A],
        research_again: true,
      }),
    ).toEqual({
      source: "rows",
      saved_filter_id: null,
      account_ids: [A, B],
      research_again: true,
    });
  });

  it("keeps a saved filter selection and drops any ids sent with it", () => {
    expect(
      cleanSelection({
        source: "filter",
        saved_filter_id: F,
        account_ids: [A],
      }),
    ).toEqual({
      source: "filter",
      saved_filter_id: F,
      account_ids: [],
      research_again: false,
    });
  });

  it.each([
    null,
    "rows",
    { source: "rows", account_ids: [] },
    { source: "rows", account_ids: ["not-an-id"] },
    { source: "rows", account_ids: Array(501).fill(A) },
    { source: "filter", saved_filter_id: "x" },
    { source: "magic", account_ids: [A] },
  ])("refuses what cannot be a selection: %j", (input) => {
    expect(cleanSelection(input)).toBeNull();
  });

  it("checks the retry choice and the confirmed figure", () => {
    expect(cleanWhich("both")).toBe("both");
    expect(cleanWhich("all")).toBeNull();
    expect(cleanConfirmed(18048)).toBe(18048);
    for (const bad of [-1, 1.5, "18048", 100_000_001, null])
      expect(cleanConfirmed(bad)).toBeNull();
  });

  it("measures progress by accounts that ended, whatever the result", () => {
    expect(progress(batch())).toEqual({ ended: 1, total: 4, percent: 25 });
    expect(
      progress(batch({ counts: { done: 2, failed: 1, not_run: 1 } })),
    ).toEqual({ ended: 4, total: 4, percent: 100 });
  });

  it("offers a retry only for an ended batch with failed or not-run accounts", () => {
    expect(retryable(batch({ counts: { failed: 2, queued: 1 } }))).toEqual({
      failed: 0,
      notRun: 0,
    });
    expect(
      retryable(
        batch({ status: "cancelled", counts: { failed: 1, not_run: 2 } }),
      ),
    ).toEqual({ failed: 1, notRun: 2 });
  });

  it("explains failures and refusals in plain words", () => {
    expect(failureText("unavailable")).toMatch(/could not be reached/);
    expect(failureText("something_new")).toBe("It could not be researched.");
    expect(failureText(null)).toBe("");
    expect(batchErrorText({ code: "batch_too_large", message: "x" })).toMatch(
      /at most 100 accounts/,
    );
    expect(
      batchErrorText({ code: null, message: "The API's own words." }),
    ).toBe("The API's own words.");
  });

  it("names what the gatherers found and leaves out empty sources", () => {
    expect(gatheredText({ sales: 2, service: 0, conversations: 1 })).toBe(
      "2 sales, 1 conversations",
    );
    expect(gatheredText({})).toBe("nothing");
  });

  it("shows the research tools only to people who may start a batch", () => {
    expect(canRunResearchBatches({ permissions: ["research_batch:run"] })).toBe(
      true,
    );
    expect(
      canRunResearchBatches({ permissions: ["account_research:run"] }),
    ).toBe(false);
  });
});

// --- Server Actions ------------------------------------------------------------------------------

describe("Server Actions", () => {
  it("asks for an estimate with only the selection", async () => {
    apiFetch.mockResolvedValue(estimate());
    const result = await estimateBatch({
      source: "rows",
      account_ids: [A],
      tenant_id: "x",
      token_cap: 1,
    });
    expect(result).toEqual({ ok: true, estimate: estimate() });
    const [path, init] = apiFetch.mock.calls[0];
    expect(path).toBe("/research-batches/estimate");
    expect(JSON.parse(init.body)).toEqual({
      source: "rows",
      saved_filter_id: null,
      account_ids: [A],
      research_again: false,
    });
  });

  it("sends nothing for a broken selection", async () => {
    const result = await estimateBatch({ source: "rows", account_ids: [] });
    expect(result.ok).toBe(false);
    expect(apiFetch).not.toHaveBeenCalled();
  });

  it("returns the API's refusal of an estimate", async () => {
    apiFetch.mockRejectedValue(
      new ApiError(503, {
        title: "Unavailable",
        status: 503,
        detail: "Off.",
        code: "agent_unavailable",
      }),
    );
    const result = await estimateBatch({ source: "rows", account_ids: [A] });
    expect(result).toMatchObject({
      ok: false,
      error: { code: "agent_unavailable" },
    });
  });

  it("starts with the confirmed figure and opens the batch's page", async () => {
    apiFetch.mockResolvedValue(batch());
    await expect(
      startBatch({ source: "filter", saved_filter_id: F }, 18048),
    ).rejects.toThrow(`REDIRECT:/accounts/batches/${F}?done=started`);
    const [path, init] = apiFetch.mock.calls[0];
    expect(path).toBe("/research-batches");
    expect(JSON.parse(init.body)).toEqual({
      source: "filter",
      saved_filter_id: F,
      account_ids: [],
      research_again: false,
      confirmed_upper_bound_tokens: 18048,
    });
  });

  it("does not start without a figure that was shown", async () => {
    const result = await startBatch(
      { source: "rows", account_ids: [A] },
      "lots",
    );
    expect(result.error.message).toMatch(/estimate first/);
    expect(apiFetch).not.toHaveBeenCalled();
  });

  it("returns a refused start (the cost moved)", async () => {
    apiFetch.mockRejectedValue(
      new ApiError(409, {
        title: "Conflict",
        status: 409,
        detail: "Moved.",
        code: "estimate_changed",
      }),
    );
    const result = await startBatch({ source: "rows", account_ids: [A] }, 1);
    expect(result.error.code).toBe("estimate_changed");
  });

  it("cancels a batch and refuses an id that is not one", async () => {
    apiFetch.mockResolvedValue(batch({ cancel_requested: true }));
    await expect(cancelBatch(F, initialDialogState)).rejects.toThrow(
      `REDIRECT:/accounts/batches/${F}?done=cancel`,
    );
    expect(apiFetch.mock.calls[0][0]).toBe(`/research-batches/${F}/cancel`);
    await expect(cancelBatch("../x", initialDialogState)).rejects.toThrow(
      "invalid batch id",
    );
  });

  it("shows a refused cancel in the dialog", async () => {
    apiFetch.mockRejectedValue(
      new ApiError(409, {
        title: "Conflict",
        status: 409,
        detail: "Not running.",
        code: "research_batch_not_running",
      }),
    );
    const state = await cancelBatch(F, initialDialogState);
    expect(state.attempt).toBe(1);
    expect(state.error?.code).toBe("research_batch_not_running");
  });

  it("estimates and starts a retry with only the choice and the figure", async () => {
    apiFetch.mockResolvedValueOnce(estimate());
    expect((await estimateRetry(F, "not_run")).ok).toBe(true);
    expect(apiFetch.mock.calls[0][0]).toBe(
      `/research-batches/${F}/retry/estimate`,
    );
    expect(JSON.parse(apiFetch.mock.calls[0][1].body)).toEqual({
      which: "not_run",
    });
    apiFetch.mockResolvedValueOnce(batch({ id: B }));
    await expect(startRetry(F, "both", 9024)).rejects.toThrow(
      `REDIRECT:/accounts/batches/${B}?done=started`,
    );
    expect(JSON.parse(apiFetch.mock.calls[1][1].body)).toEqual({
      which: "both",
      confirmed_upper_bound_tokens: 9024,
    });
  });

  it("sends no retry for a bad id or choice", async () => {
    expect((await estimateRetry("x", "failed")).ok).toBe(false);
    expect((await estimateRetry(F, "everything")).ok).toBe(false);
    expect((await startRetry(F, "failed", -5)).error).toBeTruthy();
    expect(apiFetch).not.toHaveBeenCalled();
  });
});

// --- components -----------------------------------------------------------------------------------

describe("the confirmation dialog", () => {
  it("shows the figures and starts with the upper bound it showed", async () => {
    const ask = vi.fn().mockResolvedValue({ ok: true, estimate: estimate() });
    const start = vi.fn().mockResolvedValue({
      error: {
        status: 409,
        message: "Moved.",
        code: "estimate_changed",
        requestId: null,
        fieldErrors: {},
      },
    });
    render(
      <BatchConfirm
        label="Research"
        title="Go?"
        estimate={ask}
        start={start}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Research" }));
    await screen.findByText("Accounts in the batch");
    expect(screen.getAllByText("18,048 tokens").length).toBeGreaterThan(0);
    expect(document.body.textContent).toMatch(
      /Estimated cost at most: about \$0\.03/,
    );
    fireEvent.click(screen.getByRole("button", { name: "Start research" }));
    await waitFor(() => expect(start).toHaveBeenCalledWith(18048));
    // A refused start says why in plain words and does not offer to start blindly.
    await screen.findByText(/cost changed since you looked/);
    expect(screen.queryByRole("button", { name: "Start research" })).toBeNull();
  });

  it("shows a refused estimate and nothing to start", async () => {
    const ask = vi.fn().mockResolvedValue({
      ok: false,
      error: {
        status: 422,
        message: "x",
        code: "empty_selection",
        requestId: null,
        fieldErrors: {},
      },
    });
    const start = vi.fn();
    render(
      <BatchConfirm
        label="Research"
        title="Go?"
        estimate={ask}
        start={start}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Research" }));
    await screen.findByText(/None of these accounts can be researched by you/);
    expect(screen.queryByRole("button", { name: "Start research" })).toBeNull();
    expect(start).not.toHaveBeenCalled();
  });

  it("is centred like the app's other dialogs (the style reset removes the browser's centring)", () => {
    render(
      <BatchConfirm
        label="Research"
        title="Go?"
        estimate={vi.fn()}
        start={vi.fn()}
      />,
    );
    const dialog = document.querySelector("dialog");
    expect(dialog?.className).toContain("m-auto");
    expect(dialog?.className).toContain("w-[calc(100%-2rem)]");
  });

  it("leaves out the month line when there is no budget", () => {
    render(
      <EstimateView
        estimate={estimate({
          monthly_tokens_left: null,
          estimated_cost_usd: null,
        })}
      />,
    );
    expect(screen.queryByText("Left of this month's budget")).toBeNull();
    expect(screen.queryByText(/Estimated cost/)).toBeNull();
  });
});

describe("the Accounts list's research bar", () => {
  it("reads only the ticked boxes of the selection form", () => {
    render(
      <>
        <ResearchBatchBar savedFilter={null} />
        <table>
          <tbody>
            <tr>
              <td>
                <TickAll />
                <TickBox id={A} name="Acme" />
                <TickBox id={B} name="Bolt" />
              </td>
            </tr>
          </tbody>
        </table>
        <input type="checkbox" name="account_id" value={F} defaultChecked />
      </>,
    );
    expect(tickedAccounts()).toEqual([]);
    fireEvent.click(screen.getByLabelText("Tick Bolt"));
    expect(tickedAccounts()).toEqual([B]);
    fireEvent.click(screen.getByLabelText("Tick every account on this page"));
    expect(tickedAccounts()).toEqual([A, B]); // the stray box outside the form never counts
  });

  it("offers the saved filter in use by its name, as plain text", () => {
    render(<ResearchBatchBar savedFilter={{ id: F, name: "<b>Big</b>" }} />);
    expect(
      screen.getByRole("button", {
        name: "Research every account of “<b>Big</b>”",
      }),
    ).toBeTruthy();
    expect(document.querySelector("b")).toBeNull();
  });
});

describe("the batch page", () => {
  it("hides the name of an account the viewer may not read and links the others", () => {
    render(
      <BatchItemsTable
        items={[
          item(),
          item({ position: 2, account_id: B, account_name: null }),
          item({
            position: 3,
            status: "failed",
            failure_code: "no_sourced_sentence",
            brief: null,
            brief_id: null,
          }),
        ]}
      />,
    );
    expect(
      screen.getAllByRole("link", { name: "Acme" })[0].getAttribute("href"),
    ).toBe(`/accounts/${A}`);
    expect(screen.getByText("Not available to you")).toBeTruthy();
    expect(
      screen.getByText(/nothing it could back with a record/),
    ).toBeTruthy();
    expect(
      screen.getAllByText(/3 sentences from 2 sales, 1 conversations/),
    ).toHaveLength(2);
    // The unreadable account has no "Read it" link.
    expect(screen.getAllByRole("link", { name: "Read it" })).toHaveLength(1);
  });

  it("shows the progress and the tokens", () => {
    render(<BatchSummary batch={batch()} />);
    expect(screen.getByRole("progressbar").getAttribute("aria-valuenow")).toBe(
      "1",
    );
    expect(screen.getByText(/1 of 4 accounts ended/)).toBeTruthy();
    expect(
      screen.getByText(/500 tokens used of a cap of 36,096 tokens/),
    ).toBeTruthy();
  });

  it("looks again while the batch runs, and stops once it ended", () => {
    vi.useFakeTimers();
    const { rerender } = render(<BatchAutoRefresh running refreshMs={1000} />);
    act(() => vi.advanceTimersByTime(2100));
    expect(refresh).toHaveBeenCalledTimes(2);
    rerender(<BatchAutoRefresh running={false} refreshMs={1000} />);
    act(() => vi.advanceTimersByTime(5000));
    expect(refresh).toHaveBeenCalledTimes(2);
    vi.useRealTimers();
  });

  it("offers no retry while the batch runs or when nothing failed", () => {
    const { container, rerender } = render(<RetryPanel batch={batch()} />);
    expect(container.textContent).toBe("");
    rerender(
      <RetryPanel batch={batch({ status: "finished", counts: { done: 4 } })} />,
    );
    expect(container.textContent).toBe("");
  });

  it("offers the failed, the not run, or both", () => {
    render(
      <RetryPanel
        batch={batch({
          status: "stopped_budget",
          counts: { failed: 1, not_run: 2, done: 1 },
        })}
      />,
    );
    const options = screen.getAllByRole("option").map((o) => o.textContent);
    expect(options).toEqual(["The 1 failed", "The 2 not run", "Both"]);
  });
});
