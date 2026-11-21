import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { updateLead } from "@/app/(app)/leads/[id]/actions";
import { LeadForm } from "@/components/lead-form";
import { initialLeadFormState } from "@/lib/lead-form-state";
import { validateLead } from "@/lib/validation/lead";

/** The e-mail consent answer on a lead (ADR 0036, step FM1). */

const apiFetch = vi.fn();
vi.mock("@/lib/server/api", () => ({
  apiFetch: (...a: unknown[]) => apiFetch(...a),
}));
vi.mock("next/navigation", () => ({
  usePathname: () => "/leads/new",
  redirect: (to: string) => {
    throw new Error(`REDIRECT:${to}`);
  },
}));
vi.mock("next/cache", () => ({ revalidatePath: vi.fn() }));

const LEAD = "11111111-1111-4111-8111-111111111111";

describe("validation", () => {
  it.each(["unknown", "granted", "withdrawn"])("accepts %s", (value) => {
    const result = validateLead({ last_name: "Rao", email_consent: value });
    expect(result.ok && result.data.email_consent).toBe(value);
  });

  it("treats an empty value as not on this form", () => {
    const result = validateLead({ last_name: "Rao", email_consent: "" });
    expect(result.ok && result.data.email_consent).toBeUndefined();
  });

  it.each(["yes", "GRANTED", "no"])("refuses %j", (value) => {
    const result = validateLead({ last_name: "Rao", email_consent: value });
    expect(result.ok).toBe(false);
  });
});

describe("LeadForm", () => {
  const action = async () => initialLeadFormState;

  it("shows the consent choice when editing, with the saved answer", () => {
    render(
      <LeadForm
        action={action}
        initialState={{
          ...initialLeadFormState,
          values: { last_name: "Rao", email_consent: "withdrawn" },
        }}
      />,
    );
    const select = screen.getByRole("combobox", { name: "E-mail consent" });
    expect(select).toHaveValue("withdrawn");
    expect(
      screen.getByRole("option", { name: "Opted out of e-mails" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/stops every e-mail to this person/),
    ).toBeInTheDocument();
  });

  it("does not show it on the new-lead form", () => {
    render(<LeadForm action={action} initialState={initialLeadFormState} />);
    expect(
      screen.queryByRole("combobox", { name: "E-mail consent" }),
    ).toBeNull();
  });
});

describe("updateLead", () => {
  function form(values: Record<string, string>) {
    const data = new FormData();
    data.set("version", "3");
    data.set("last_name", "Rao");
    for (const [k, v] of Object.entries(values)) data.set(k, v);
    return data;
  }

  it("sends the answer when the form carries it", async () => {
    apiFetch.mockResolvedValue({});
    await expect(
      updateLead(
        LEAD,
        initialLeadFormState,
        form({ email_consent: "withdrawn" }),
      ),
    ).rejects.toThrow(`REDIRECT:/leads/${LEAD}`);
    const body = JSON.parse(apiFetch.mock.calls[0][1].body as string);
    expect(body.email_consent).toBe("withdrawn");
  });

  it("leaves it out when the form does not carry it, so a save can never reset a no", async () => {
    apiFetch.mockReset();
    apiFetch.mockResolvedValue({});
    await expect(
      updateLead(LEAD, initialLeadFormState, form({})),
    ).rejects.toThrow("REDIRECT");
    const body = JSON.parse(apiFetch.mock.calls[0][1].body as string);
    expect("email_consent" in body).toBe(false);
  });
});
