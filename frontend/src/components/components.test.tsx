import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import {
  initialLeadFormState,
  type LeadFormState,
} from "@/lib/lead-form-state";
import { LeadForm } from "@/components/lead-form";
import { AppShell } from "@/components/app-shell";
import { ModuleGrid } from "@/components/module-grid";
import { Pagination } from "@/components/pagination";
import { ErrorAlert } from "@/components/ui";
import { modulesFor } from "@/lib/modules";

type Action = (
  state: LeadFormState,
  formData: FormData,
) => Promise<LeadFormState>;

vi.mock("next/navigation", () => ({ usePathname: () => "/leads" }));
vi.mock("@/app/actions/auth", () => ({ logout: vi.fn() }));

const { UserMenu } = await import("@/components/user-menu");

describe("LeadForm", () => {
  it("shows errors and does not submit when required data is missing", async () => {
    const action = vi.fn<Action>(async (state) => state);
    const user = userEvent.setup();
    render(<LeadForm action={action} initialState={initialLeadFormState} />);

    await user.type(screen.getByLabelText(/e-mail/i), "not-an-email");
    await user.click(screen.getByRole("button", { name: "Create lead" }));

    expect(action).not.toHaveBeenCalled();
    expect(
      screen.getByText("Please correct 2 fields below."),
    ).toBeInTheDocument();
    const lastName = screen.getByLabelText(/last name/i);
    expect(lastName).toHaveAttribute("aria-invalid", "true");
    expect(lastName).toHaveAccessibleDescription("Last name is required.");
    expect(lastName).toHaveFocus(); // keyboard users land on the first problem
    expect(screen.getByLabelText(/e-mail/i)).toHaveAccessibleDescription(
      /valid e-mail/,
    );
  });

  it("submits valid data to the server action", async () => {
    const action = vi.fn<Action>(async (state) => state);
    const user = userEvent.setup();
    render(<LeadForm action={action} initialState={initialLeadFormState} />);

    await user.type(screen.getByLabelText(/first name/i), "Jamie");
    await user.type(screen.getByLabelText(/last name/i), "Example");
    await user.selectOptions(screen.getByLabelText(/source/i), "referral");
    await user.click(screen.getByRole("button", { name: "Create lead" }));

    expect(action).toHaveBeenCalledOnce();
    const formData = action.mock.calls[0][1];
    expect(formData.get("last_name")).toBe("Example");
    expect(formData.get("source")).toBe("referral");
  });

  it("shows the backend's error and field messages, keeping what was typed", () => {
    const state: LeadFormState = {
      attempt: 1,
      values: { last_name: "Example", email: "dup@example.test" },
      fieldErrors: { email: "This e-mail is not accepted." },
      error: {
        status: 422,
        message: "The request contains invalid data.",
        code: null,
        requestId: "abc123",
        fieldErrors: {},
      },
    };
    render(<LeadForm action={vi.fn()} initialState={state} />);

    const alert = screen.getAllByRole("alert")[0];
    expect(
      within(alert).getByText("The lead could not be created"),
    ).toBeInTheDocument();
    expect(within(alert).getByText("abc123")).toBeInTheDocument();
    expect(screen.getByLabelText(/last name/i)).toHaveValue("Example");
    expect(screen.getByLabelText(/e-mail/i)).toHaveAccessibleDescription(
      "This e-mail is not accepted.",
    );
  });

  it("labels every field and marks the required one", () => {
    render(<LeadForm action={vi.fn()} initialState={initialLeadFormState} />);

    for (const label of [
      /first name/i,
      /last name/i,
      /e-mail/i,
      /phone/i,
      /company/i,
      /job title/i,
      /source/i,
    ]) {
      expect(screen.getByLabelText(label)).toBeInTheDocument();
    }
    expect(screen.getByLabelText(/last name/i)).toBeRequired();
  });
});

describe("Pagination", () => {
  const href = (page: number) => `/leads?page=${page}`;

  it("shows the range and both links in the middle of a list", () => {
    render(<Pagination total={57} page={2} pageSize={20} hrefForPage={href} />);

    expect(screen.getByText("Showing 21–40 of 57")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Previous" })).toHaveAttribute(
      "href",
      "/leads?page=1",
    );
    expect(screen.getByRole("link", { name: "Next" })).toHaveAttribute(
      "href",
      "/leads?page=3",
    );
  });

  it("disables links at the edges", () => {
    render(<Pagination total={5} page={1} pageSize={20} hrefForPage={href} />);

    expect(screen.queryByRole("link")).toBeNull();
    expect(screen.getByText("Previous")).toHaveAttribute(
      "aria-disabled",
      "true",
    );
    expect(screen.getByText("Next")).toHaveAttribute("aria-disabled", "true");
  });
});

describe("AppShell navigation", () => {
  const nav = [
    { href: "/", label: "Dashboard", icon: "home" as const },
    { href: "/leads", label: "Leads", icon: "leads" as const },
  ];

  it("marks the current page and offers a skip link", () => {
    render(
      <AppShell nav={nav} userMenu={null}>
        <p>content</p>
      </AppShell>,
    );

    const main = screen.getAllByRole("navigation", { name: "Main" })[0];
    expect(within(main).getByRole("link", { name: "Leads" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(
      within(main).getByRole("link", { name: "Dashboard" }),
    ).not.toHaveAttribute("aria-current");
    expect(
      screen.getByRole("link", { name: "Skip to main content" }),
    ).toHaveAttribute("href", "#main");
  });

  it("opens the mobile menu and closes it with Escape", async () => {
    const user = userEvent.setup();
    render(
      <AppShell nav={nav} userMenu={null}>
        <p>content</p>
      </AppShell>,
    );

    await user.click(screen.getByRole("button", { name: "Open menu" }));
    expect(
      screen.getByRole("dialog", { name: "Main menu" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Close menu" })).toHaveFocus();

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});

describe("UserMenu", () => {
  it("is keyboard operable and shows roles and sign-out", async () => {
    const user = userEvent.setup();
    render(
      <UserMenu
        name="Avery Agent"
        email="agent1@alpha.example.test"
        roles={["sales_agent"]}
      />,
    );

    const button = screen.getByRole("button", { name: /account menu/i });
    button.focus();
    await user.keyboard("{Enter}");
    expect(button).toHaveAttribute("aria-expanded", "true");
    expect(
      screen.getByRole("button", { name: "Sign out" }),
    ).toBeInTheDocument();
    expect(screen.getAllByText("Sales Agent").length).toBeGreaterThan(0);

    await user.keyboard("{Escape}");
    expect(button).toHaveAttribute("aria-expanded", "false");
    expect(button).toHaveFocus();
  });
});

describe("ErrorAlert", () => {
  it("is announced and shows a reference for support", () => {
    render(
      <ErrorAlert
        error={{
          status: 503,
          message: "Try again shortly.",
          code: null,
          requestId: "req-9",
          fieldErrors: {},
        }}
      />,
    );

    expect(screen.getByRole("alert")).toHaveTextContent("Try again shortly.");
    expect(screen.getByText("req-9")).toBeInTheDocument();
  });
});

describe("ModuleGrid", () => {
  it("links only to available modules and labels the rest", () => {
    render(
      <ModuleGrid modules={modulesFor({ permissions: ["lead:read:own"] })} />,
    );

    expect(
      screen.getByRole("heading", { name: "CRM modules" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText("16 of 20 available · more are added phase by phase"),
    ).toBeInTheDocument();
    const links = screen.getAllByRole("link");
    expect(links).toHaveLength(1);
    expect(links[0]).toHaveAttribute("href", "/leads");
    expect(links[0]).toHaveTextContent("Lead Management");
    expect(
      screen.getByLabelText("Marketing: Planned. Planned · phase 16."),
    ).toBeInTheDocument();
    expect(
      screen.getByLabelText(
        "Customer Management: Available. Not included in your role.",
      ),
    ).toBeInTheDocument();
    expect(screen.getAllByRole("listitem")).toHaveLength(20);
  });
});
