import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextRequest } from "next/server";
import { afterEach, describe, expect, it, vi } from "vitest";

import { pickedAccount } from "@/components/account-picker";
import { AccountForm, ContactForm } from "@/components/customer-forms";
import { initialFormState, type FormState } from "@/lib/form-state";

const ACME = { id: "11111111-1111-4111-8111-111111111111", name: "Acme Ltd" };
const OTHER = {
  id: "22222222-2222-4222-8222-222222222222",
  name: "Other GmbH",
};

const apiFetch = vi.fn();
vi.mock("@/lib/server/api", () => ({
  apiFetch: (path: string) => apiFetch(path),
}));

function mockSearch(result: unknown) {
  const fetchMock = vi.fn<(url: string) => Promise<Response>>(
    async () =>
      new Response(JSON.stringify(result), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
  );
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => {
  vi.unstubAllGlobals();
  apiFetch.mockReset();
});

describe("pickedAccount", () => {
  it("uses the default before anything was submitted", () => {
    expect(pickedAccount({}, "account_id", "account_label", ACME)).toEqual(
      ACME,
    );
    expect(pickedAccount({}, "account_id", "account_label")).toBeNull();
  });

  it("shows what the user had chosen after a failed submit", () => {
    const values = { account_id: OTHER.id, account_label: OTHER.name };
    expect(pickedAccount(values, "account_id", "account_label", ACME)).toEqual(
      OTHER,
    );
  });

  it("does not refill a cleared field with the default", () => {
    const cleared = { account_id: "", account_label: "" };
    expect(
      pickedAccount(cleared, "account_id", "account_label", ACME),
    ).toBeNull();
  });

  it("ignores an id that has no name to show", () => {
    expect(
      pickedAccount({ account_id: OTHER.id }, "account_id", "account_label"),
    ).toBeNull();
  });
});

const failedState = (values: Record<string, string>): FormState => ({
  ...initialFormState,
  attempt: 1,
  values,
  fieldErrors: { last_name: "Last name is required." },
});

describe("ContactForm account field", () => {
  const props = {
    action: vi.fn(async (state: FormState) => state),
    cancelHref: "/contacts",
    submitLabel: "Create contact",
  };

  it("starts with the account the page was opened from", () => {
    render(
      <ContactForm
        {...props}
        initialState={initialFormState}
        defaultAccount={ACME}
      />,
    );
    expect(screen.getByRole("combobox", { name: /Account/ })).toHaveValue(
      "Acme Ltd",
    );
    const form = screen
      .getByRole("combobox", { name: /Account/ })
      .closest("form");
    expect(new FormData(form as HTMLFormElement).get("account_id")).toBe(
      ACME.id,
    );
  });

  it("is optional: empty posts no account", () => {
    render(<ContactForm {...props} initialState={initialFormState} />);
    const box = screen.getByRole("combobox", { name: /Account/ });
    expect(box).toHaveValue("");
    expect(box).toHaveAttribute("placeholder", "No account - type to search");
    const form = box.closest("form") as HTMLFormElement;
    expect(new FormData(form).get("account_id")).toBe("");
  });

  it("keeps the chosen account after a validation error", () => {
    render(
      <ContactForm
        {...props}
        initialState={failedState({
          account_id: OTHER.id,
          account_label: OTHER.name,
        })}
        defaultAccount={ACME}
      />,
    );
    expect(screen.getByRole("combobox", { name: /Account/ })).toHaveValue(
      "Other GmbH",
    );
  });
});

describe("AccountForm parent field", () => {
  const props = {
    action: vi.fn(async (state: FormState) => state),
    cancelHref: "/accounts",
    submitLabel: "Save changes",
  };

  it("never offers the account itself as its own parent", async () => {
    const fetchMock = mockSearch([OTHER]);
    render(
      <AccountForm
        {...props}
        initialState={initialFormState}
        account={
          { id: ACME.id, name: ACME.name, version: 1 } as unknown as Parameters<
            typeof AccountForm
          >[0]["account"]
        }
      />,
    );
    await userEvent
      .setup()
      .click(screen.getByRole("combobox", { name: /Parent account/ }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(String(fetchMock.mock.calls.at(-1)?.[0])).toBe(
      `/accounts/search?q=&exclude=${ACME.id}`,
    );
  });

  it("posts the parent under its own field names", async () => {
    mockSearch([OTHER]);
    render(<AccountForm {...props} initialState={initialFormState} />);
    const user = userEvent.setup();
    const box = screen.getByRole("combobox", { name: /Parent account/ });
    await user.type(box, "oth");
    await user.click(await screen.findByRole("option", { name: "Other GmbH" }));
    const data = new FormData(box.closest("form") as HTMLFormElement);
    expect(data.get("parent_account_id")).toBe(OTHER.id);
    expect(data.get("parent_account_label")).toBe("Other GmbH");
  });
});

describe("GET /accounts/search", () => {
  const item = (a: { id: string; name: string }) => ({ ...a, other: "x" });

  it("returns only id and name, at most 20", async () => {
    const { GET } = await import("@/app/(app)/accounts/search/route");
    apiFetch.mockResolvedValue({ items: [item(ACME), item(OTHER)] });
    const response = await GET(
      new NextRequest("http://localhost/accounts/search?q=%20ac%20"),
    );
    expect(await response.json()).toEqual([ACME, OTHER]);
    expect(apiFetch).toHaveBeenCalledWith("/accounts?limit=20&q=ac");
  });

  it("leaves the excluded account out and asks for one extra row", async () => {
    const { GET } = await import("@/app/(app)/accounts/search/route");
    apiFetch.mockResolvedValue({ items: [item(ACME), item(OTHER)] });
    const response = await GET(
      new NextRequest(`http://localhost/accounts/search?exclude=${ACME.id}`),
    );
    expect(await response.json()).toEqual([OTHER]);
    expect(apiFetch).toHaveBeenCalledWith("/accounts?limit=21");
  });

  it("ignores an exclude value that is not an id", async () => {
    const { GET } = await import("@/app/(app)/accounts/search/route");
    apiFetch.mockResolvedValue({ items: [item(ACME)] });
    await GET(
      new NextRequest("http://localhost/accounts/search?exclude=not-an-id"),
    );
    expect(apiFetch).toHaveBeenCalledWith("/accounts?limit=20");
  });
});
