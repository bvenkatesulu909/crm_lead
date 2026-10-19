import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import {
  AddStaffUserButton,
  ApproveRequestButton,
} from "@/app/(app)/users/user-dialogs";
import type { DialogState } from "@/lib/dialog-state";
import { navigationFor } from "@/lib/permissions";

/** ADR 0004: user administration dialogs and navigation (display only - the API decides). */

type Bound = (state: DialogState, formData: FormData) => Promise<DialogState>;
const failing: Bound = async (state) => ({
  ...state,
  attempt: state.attempt + 1,
  fieldErrors: {
    account_ids: "Choose at least one account the customer may see.",
  },
});

describe("ApproveRequestButton", () => {
  it("still sends 'customer' after a failed submit (form reset must not change the role)", async () => {
    const action = vi.fn<Bound>(failing);
    const user = userEvent.setup();
    render(<ApproveRequestButton name="Casey" email="casey@example.test" accounts={[{ id: "a1", name: "Acme" }]} action={action} />);

    await user.click(screen.getByRole("button", { name: "Approve" }));
    const dialog = screen.getByRole("dialog", { name: "Approve Casey" });
    await user.selectOptions(within(dialog).getByLabelText("Role"), "customer");
    await user.click(within(dialog).getByRole("button", { name: "Approve" }));
    expect(await within(dialog).findByText(/Choose at least one account/)).toBeInTheDocument();

    expect(within(dialog).getByLabelText("Role")).toHaveValue("customer");
    await user.click(within(dialog).getByLabelText("Acme"));
    await user.click(within(dialog).getByRole("button", { name: "Approve" }));
    const sent = action.mock.calls[1][1];
    expect([sent.get("role"), sent.getAll("account_ids")]).toEqual(["customer", ["a1"]]);
  });

  it("shows account choices only for customers", async () => {
    const user = userEvent.setup();
    render(<ApproveRequestButton name="Casey" email="c@example.test" accounts={[{ id: "a1", name: "Acme" }]} action={vi.fn<Bound>()} />);
    await user.click(screen.getByRole("button", { name: "Approve" }));
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).queryByLabelText("Acme")).not.toBeInTheDocument();
    await user.selectOptions(within(dialog).getByLabelText("Role"), "customer");
    expect(within(dialog).getByLabelText("Acme")).toBeInTheDocument();
  });

  it("never offers Super Admin", async () => {
    const user = userEvent.setup();
    render(<ApproveRequestButton name="X" email="x@example.test" accounts={[]} action={vi.fn<Bound>()} />);
    await user.click(screen.getByRole("button", { name: "Approve" }));
    const options = within(screen.getByRole("dialog")).getAllByRole("option").map((o) => (o as HTMLOptionElement).value);
    expect(options).toEqual(["tenant_admin", "sales_manager", "sales_agent", "support_agent", "customer"]);
  });
}); // prettier-ignore

describe("labels point at their own dialog's fields", () => {
  it("two dialogs on one page get different field ids", () => {
    render(<><AddStaffUserButton action={vi.fn<Bound>()} /><AddStaffUserButton action={vi.fn<Bound>()} /></>);
    const ids = [...document.querySelectorAll("select[name=role]")].map((e) => e.id);
    expect(new Set(ids).size).toBe(2);
  });
}); // prettier-ignore

describe("navigation", () => {
  it("shows Users only to tenant admins and Organisations only to platform admins", () => {
    const labels = (permissions: string[], user_type: "staff" | "platform") => navigationFor({ permissions, user_type }).map((i) => i.label);
    expect(labels(["tenant:user:read"], "staff")).toContain("Users");
    expect(labels(["lead:read:own"], "staff")).not.toContain("Users");
    expect(labels(["platform:tenant:read"], "platform")).toEqual(["Dashboard", "Organisations"]);
  });
}); // prettier-ignore
