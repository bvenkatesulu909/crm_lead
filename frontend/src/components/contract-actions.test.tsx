import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ContractActions } from "@/app/(app)/contracts/[id]/contract-actions";
import type { ContractStatus } from "@/lib/api-types";

vi.mock("next/navigation", () => ({ usePathname: () => "/contracts/1" }));

const stub = async () => ({ attempt: 0, fieldErrors: {}, error: null });
const act = { activate: stub, terminate: stub, renew: stub, note: stub };

/** The buttons a person sees for a contract in this state (display only - the API decides). */
function shown(
  status: ContractStatus,
  can: { write: boolean; manage: boolean },
  hasRenewal = false,
): string[] {
  const { unmount } = render(
    <ContractActions
      id="abc"
      status={status}
      hasRenewal={hasRenewal}
      can={can}
      act={act}
    />,
  );
  const group = screen.getByRole("group", { name: "Contract actions" });
  // Only the visible triggers: the dialogs' own buttons (Cancel, confirm) live inside <dialog>.
  const names = [...group.querySelectorAll("a, button")]
    .filter((el) => el.closest("dialog") === null)
    .map((el) => el.textContent?.trim() ?? "");
  unmount();
  return names;
}

const manager = { write: true, manage: true };
const agent = { write: true, manage: false };
const reader = { write: false, manage: false };

describe("ContractActions", () => {
  it("a draft: the agent can edit and note; only a manager can activate", () => {
    expect(shown("draft", agent)).toEqual(["Edit", "Add note"]);
    expect(shown("draft", manager)).toEqual(["Edit", "Activate", "Add note"]);
  });

  it("an active contract: edit, renew, terminate - the last two for managers only", () => {
    expect(shown("active", agent)).toEqual(["Edit", "Add note"]);
    expect(shown("active", manager)).toEqual([
      "Edit",
      "Renew",
      "Terminate",
      "Add note",
    ]);
  });

  it("a renewal can only be made once", () => {
    expect(shown("active", manager, true)).toEqual([
      "Edit",
      "Terminate",
      "Add note",
    ]);
    expect(shown("expired", manager, true)).toEqual(["Add note"]);
  });

  it("an expired contract can still be renewed, but not edited or terminated", () => {
    expect(shown("expired", manager)).toEqual(["Renew", "Add note"]);
    expect(shown("expired", agent)).toEqual(["Add note"]);
  });

  it("terminated and renewed contracts are final", () => {
    for (const status of ["terminated", "renewed"] as const) {
      expect(shown(status, manager)).toEqual(["Add note"]);
      expect(shown(status, agent)).toEqual(["Add note"]);
    }
  });

  it("someone who may only read sees no buttons at all", () => {
    for (const status of [
      "draft",
      "active",
      "expired",
      "terminated",
      "renewed",
    ] as const)
      expect(shown(status, reader)).toEqual([]);
  });
});
