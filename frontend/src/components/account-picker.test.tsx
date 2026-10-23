import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AccountPicker } from "@/components/account-picker";

const ACME = { id: "11111111-1111-4111-8111-111111111111", name: "Acme Ltd" };
const BETA = { id: "22222222-2222-4222-8222-222222222222", name: "Beta GmbH" };

/** Renders the picker inside a form, so what the browser would submit can be inspected. */
function setup(defaultAccount?: typeof ACME | null) {
  render(
    <form aria-label="test form">
      <label htmlFor="acc">Account</label>
      <AccountPicker id="acc" defaultAccount={defaultAccount} />
    </form>,
  );
  const form = screen.getByRole("form") as HTMLFormElement;
  const submitted = () => {
    const data = new FormData(form);
    return {
      id: String(data.get("account_id")),
      label: String(data.get("account_label")),
    };
  };
  return { form, submitted };
}

function mockSearch(result: unknown, ok = true) {
  const fetchMock = vi.fn<(url: string) => Promise<Response>>(
    async () =>
      new Response(JSON.stringify(result), {
        status: ok ? 200 : 500,
        headers: { "content-type": "application/json" },
      }),
  );
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => vi.unstubAllGlobals());

describe("AccountPicker", () => {
  it("starts empty and submits no account until one is chosen", () => {
    const { submitted } = setup();
    expect(screen.getByRole("combobox", { name: "Account" })).toHaveValue("");
    expect(submitted()).toEqual({ id: "", label: "" });
  });

  it("asks the server for matches while typing and submits the chosen account", async () => {
    const fetchMock = mockSearch([ACME, BETA]);
    const { submitted } = setup();
    const user = userEvent.setup();

    await user.type(screen.getByRole("combobox", { name: "Account" }), "ac");
    const option = await screen.findByRole("option", { name: "Acme Ltd" });
    expect(
      screen.getByRole("option", { name: "Beta GmbH" }),
    ).toBeInTheDocument();
    expect(String(fetchMock.mock.calls.at(-1)?.[0])).toBe(
      "/accounts/search?q=ac",
    );

    await user.click(option);
    expect(screen.getByRole("combobox", { name: "Account" })).toHaveValue(
      "Acme Ltd",
    );
    expect(submitted()).toEqual({ id: ACME.id, label: "Acme Ltd" });
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });

  it("works from the keyboard: arrows move, Enter chooses without submitting", async () => {
    mockSearch([ACME, BETA]);
    const { form, submitted } = setup();
    const onSubmit = vi.fn((event: Event) => event.preventDefault());
    form.addEventListener("submit", onSubmit);
    const user = userEvent.setup();

    await user.type(screen.getByRole("combobox", { name: "Account" }), "b");
    await screen.findByRole("option", { name: "Beta GmbH" });
    await user.keyboard("{ArrowDown}{Enter}");

    expect(submitted().id).toBe(BETA.id);
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("forgets the choice as soon as the text is edited again", async () => {
    mockSearch([ACME]);
    const { submitted } = setup(ACME);
    expect(submitted().id).toBe(ACME.id);

    await userEvent
      .setup()
      .type(screen.getByRole("combobox", { name: "Account" }), "x");
    expect(submitted()).toEqual({ id: "", label: "" });
  });

  it("says so when nothing matches, and when the search fails", async () => {
    mockSearch([]);
    const user = userEvent.setup();
    setup();
    await user.type(screen.getByRole("combobox", { name: "Account" }), "zzz");
    expect(await screen.findByText("No account matches.")).toBeInTheDocument();

    mockSearch({ error: "boom" }, false);
    await user.type(screen.getByRole("combobox", { name: "Account" }), "z");
    await waitFor(() =>
      expect(
        screen.getByText("The accounts could not be loaded. Try typing again."),
      ).toBeInTheDocument(),
    );
  });

  it("shows a pre-chosen account (e.g. after a validation error)", () => {
    const { submitted } = setup(BETA);
    expect(screen.getByRole("combobox", { name: "Account" })).toHaveValue(
      "Beta GmbH",
    );
    expect(submitted()).toEqual({ id: BETA.id, label: "Beta GmbH" });
  });
});
