// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  deleteSavedFilter,
  saveFilter,
} from "@/app/(app)/accounts/saved-filter-actions";
import { SavedFiltersBar } from "@/components/saved-filters-bar";
import { ApiError } from "@/lib/api-error";
import { initialDialogState } from "@/lib/dialog-state";
import {
  hasHiddenConditions,
  hrefForSavedFilter,
  matchesList,
  paramsFromList,
  type SavedFilter,
} from "@/lib/saved-filters";

const apiFetch = vi.fn();
vi.mock("@/lib/server/api", () => ({
  apiFetch: (...a: unknown[]) => apiFetch(...a),
}));
vi.mock("next/cache", () => ({ revalidatePath: vi.fn() }));
vi.mock("next/navigation", () => ({
  redirect: (to: string) => {
    throw new Error(`REDIRECT:${to}`);
  },
}));

const ID = "11111111-1111-4111-8111-111111111111";
const EMPTY = { q: "", status: "", segment: "", country: "", lifecycle: "" };

function filter(changes: Partial<SavedFilter> = {}): SavedFilter {
  return {
    id: ID,
    record_type: "account",
    name: "Big accounts",
    params: { segment: "enterprise", lifecycle_stage: "at_risk" },
    shared: false,
    owner_user_id: "u1",
    mine: true,
    version: 1,
    created_at: "2026-11-21T10:00:00Z",
    updated_at: "2026-11-21T10:00:00Z",
    ...changes,
  };
}

beforeEach(() => {
  apiFetch.mockReset();
});

describe("saved filter helpers", () => {
  it("keeps only the conditions that are set, in the API's names", () => {
    expect(
      paramsFromList({ ...EMPTY, segment: "enterprise", lifecycle: "at_risk" }),
    ).toEqual({ segment: "enterprise", lifecycle_stage: "at_risk" });
    expect(paramsFromList(EMPTY)).toEqual({});
  });

  it("builds the list address that applies a filter", () => {
    expect(hrefForSavedFilter(filter())).toBe(
      "/accounts?segment=enterprise&lifecycle=at_risk",
    );
    expect(hrefForSavedFilter(filter({ params: {} }))).toBe("/accounts");
  });

  it("leaves out, and reports, a condition the list has no box for", () => {
    const odd = filter({ params: { segment: "enterprise", owner_id: ID } });
    expect(hrefForSavedFilter(odd)).toBe("/accounts?segment=enterprise");
    expect(hasHiddenConditions(odd)).toBe(true);
    expect(hasHiddenConditions(filter())).toBe(false);
  });

  it("recognises the filter that is currently applied", () => {
    const list = { ...EMPTY, segment: "enterprise", lifecycle: "at_risk" };
    expect(matchesList(filter(), list)).toBe(true);
    expect(matchesList(filter(), { ...list, q: "x" })).toBe(false);
    expect(matchesList(filter(), EMPTY)).toBe(false);
  });
});

describe("saving a filter", () => {
  function form(values: Record<string, string>) {
    const data = new FormData();
    for (const [k, v] of Object.entries(values)) data.set(k, v);
    return data;
  }

  it("sends only the name, the share choice and the list's conditions", async () => {
    apiFetch.mockResolvedValue(filter());
    await expect(
      saveFilter(
        initialDialogState,
        form({
          name: " Big accounts ",
          shared: "on",
          segment: "enterprise",
          // None of these may travel: they are not conditions of the list.
          owner_user_id: "x",
          tenant_id: "y",
          archived: "true",
        }),
      ),
    ).rejects.toThrow(`REDIRECT:/accounts?segment=enterprise&saved=${ID}`);
    const [path, init] = apiFetch.mock.calls[0] as [string, RequestInit];
    expect(path).toBe("/saved-filters");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({
      name: "Big accounts",
      params: { segment: "enterprise" },
      shared: true,
    });
  });

  it("does not share unless asked", async () => {
    apiFetch.mockResolvedValue(filter());
    await saveFilter(
      initialDialogState,
      form({ name: "A", segment: "enterprise" }),
    ).catch(() => undefined);
    const init = apiFetch.mock.calls[0][1] as RequestInit;
    expect(JSON.parse(init.body as string).shared).toBe(false);
  });

  it("refuses to save an empty filter without calling the API", async () => {
    const state = await saveFilter(initialDialogState, form({ name: "A" }));
    expect(state.error).not.toBeNull();
    expect(apiFetch).not.toHaveBeenCalled();
  });

  it("shows the API's reason and keeps the dialog open", async () => {
    apiFetch.mockRejectedValue(
      new ApiError(409, {
        title: "Conflict",
        status: 409,
        detail: "You already have a filter with this name.",
        code: "saved_filter_name_taken",
      }),
    );
    const state = await saveFilter(
      initialDialogState,
      form({ name: "A", segment: "enterprise" }),
    );
    expect(state.attempt).toBe(1);
    expect(state.error?.message).toMatch(/already have a filter/);
  });
});

describe("deleting a filter", () => {
  it("refuses an id that is not an id before any call", async () => {
    await expect(
      deleteSavedFilter("../accounts", initialDialogState),
    ).rejects.toThrow("invalid filter id");
    expect(apiFetch).not.toHaveBeenCalled();
  });

  it("deletes through the API and returns to the list", async () => {
    apiFetch.mockResolvedValue(undefined);
    await expect(deleteSavedFilter(ID, initialDialogState)).rejects.toThrow(
      "REDIRECT:/accounts?done=filter-deleted",
    );
    expect(apiFetch).toHaveBeenCalledWith(`/saved-filters/${ID}`, {
      method: "DELETE",
    });
  });

  it("shows the API's refusal, e.g. someone else's filter", async () => {
    apiFetch.mockRejectedValue(
      new ApiError(403, {
        title: "Forbidden",
        status: 403,
        detail: "Only the owner can change this filter.",
        code: "forbidden",
      }),
    );
    const state = await deleteSavedFilter(ID, initialDialogState);
    expect(state.error?.status).toBe(403);
    expect(state.error?.message).toMatch(/permission/);
  });
});

describe("the saved filters bar", () => {
  function bar(props: Partial<Parameters<typeof SavedFiltersBar>[0]> = {}) {
    return render(
      <SavedFiltersBar
        filters={[]}
        list={EMPTY}
        filtered={false}
        canShare={false}
        {...props}
      />,
    );
  }

  it("says when there are none and offers no save without a condition", () => {
    bar();
    expect(screen.getByText("None yet.")).toBeTruthy();
    expect(
      screen.queryByRole("button", { name: "Save this filter" }),
    ).toBeNull();
  });

  it("lists filters as links that apply them", () => {
    bar({ filters: [filter()] });
    expect(
      screen.getByRole("link", { name: "Big accounts" }).getAttribute("href"),
    ).toBe("/accounts?segment=enterprise&lifecycle=at_risk");
  });

  it("marks the applied filter and does not offer to save it again", () => {
    bar({
      filters: [filter()],
      list: { ...EMPTY, segment: "enterprise", lifecycle: "at_risk" },
      filtered: true,
    });
    expect(
      screen
        .getByRole("link", { name: "Big accounts" })
        .getAttribute("aria-current"),
    ).toBe("true");
    expect(
      screen.queryByRole("button", { name: "Save this filter" }),
    ).toBeNull();
  });

  it("offers to save a filter that is in use but not saved", () => {
    bar({ list: { ...EMPTY, segment: "enterprise" }, filtered: true });
    expect(
      screen.getByRole("button", { name: "Save this filter" }),
    ).toBeTruthy();
  });

  it("offers sharing only to those who may share", () => {
    const { unmount } = bar({
      list: { ...EMPTY, segment: "enterprise" },
      filtered: true,
      canShare: false,
    });
    expect(screen.queryByText(/Share with everyone/)).toBeNull();
    unmount();
    bar({
      list: { ...EMPTY, segment: "enterprise" },
      filtered: true,
      canShare: true,
    });
    expect(screen.getByText(/Share with everyone/)).toBeTruthy();
  });

  it("lets only the owner delete, and labels a colleague's shared filter", () => {
    bar({
      filters: [
        filter({ id: "a", name: "Mine" }),
        filter({ id: "b", name: "Theirs", mine: false, shared: true }),
      ],
    });
    expect(screen.getAllByRole("button", { name: "Delete" })).toHaveLength(1);
    expect(screen.getByText("(team)")).toBeTruthy();
  });

  it("shows a filter's name as plain text, never as markup", () => {
    const { container } = bar({
      filters: [filter({ name: "<img src=x onerror=alert(1)>" })],
    });
    expect(container.querySelector("img")).toBeNull();
    expect(screen.getByText("<img src=x onerror=alert(1)>")).toBeTruthy();
  });

  it("says when a filter holds conditions the list cannot show", () => {
    bar({ filters: [filter({ params: { owner_id: ID } })] });
    expect(screen.getByText("(partly shown)")).toBeTruthy();
  });

  it("keeps the typed name and the share choice after a refused save", async () => {
    apiFetch.mockRejectedValue(
      new ApiError(409, {
        title: "Conflict",
        status: 409,
        detail: "You already have a filter with this name.",
        code: "saved_filter_name_taken",
      }),
    );
    bar({
      list: { ...EMPTY, segment: "enterprise" },
      filtered: true,
      canShare: true,
    });
    const name = screen.getByLabelText("Name", {
      selector: "input",
    }) as HTMLInputElement;
    fireEvent.change(name, { target: { value: "Big accounts" } });
    fireEvent.click(screen.getByLabelText(/Share with everyone/));
    fireEvent.click(
      screen.getByRole("button", { name: "Save filter", hidden: true }),
    );
    await waitFor(() =>
      expect(
        screen.getAllByText(/already have a filter/).length,
      ).toBeGreaterThan(0),
    );
    const after = screen.getByLabelText("Name", {
      selector: "input",
    }) as HTMLInputElement;
    expect(after.value).toBe("Big accounts");
    expect(
      (screen.getByLabelText(/Share with everyone/) as HTMLInputElement)
        .checked,
    ).toBe(true);
  });
});
