import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { EmailComposer } from "@/components/email-composer";
import { EmailStatusBadge } from "@/components/email-views";
import type { Me } from "@/lib/api-types";
import {
  blockedReason,
  checkMessage,
  checkTemplate,
  emailPageHref,
  emailQuery,
  failureText,
  messageRecordHref,
  parseEmailFilters,
  placeholderProblems,
  recipientOptions,
  recordPath,
} from "@/lib/communications";
import { modulesFor } from "@/lib/modules";
import {
  PERMISSION_LABELS,
  canManageEmailTemplates,
  canReadEmailCenter,
  canReadEmailHistory,
  canSendEmails,
  navigationFor,
} from "@/lib/permissions";

const ID = "11111111-2222-4333-8444-555555555555";
const stub = async () => ({ attempt: 0, fieldErrors: {}, error: null });

describe("Communication Center list filters", () => {
  it("keeps only known values and clamps the page", () => {
    expect(parseEmailFilters({ q: "  hello  ", status: "sent", direction: "outbound", page: "3" })).toEqual({
      q: "hello", status: "sent", direction: "outbound", page: 3,
    });
    expect(parseEmailFilters({ status: "lost", direction: "sideways", page: "-4" })).toEqual({
      q: "", status: "", direction: "", page: 1,
    });
    expect(parseEmailFilters({ q: "x".repeat(150), page: "999999" }).q).toHaveLength(100);
    expect(parseEmailFilters({ page: "999999" }).page).toBe(5000);
  }); // prettier-ignore

  it("builds the API query and the page links", () => {
    const filters = parseEmailFilters({ q: "quote", status: "failed", page: "2" });
    expect(emailQuery(filters, 25).toString()).toBe("limit=25&offset=25&q=quote&status=failed");
    expect(emailPageHref(filters, 1)).toBe("/communications?q=quote&status=failed");
    expect(emailPageHref(parseEmailFilters({}), 1)).toBe("/communications");
    expect(emailPageHref(parseEmailFilters({}), 4)).toBe("/communications?page=4");
  }); // prettier-ignore

  it("links an e-mail to its lead or contact", () => {
    expect(messageRecordHref({ lead_id: ID, contact_id: null })).toBe(`/leads/${ID}`);
    expect(messageRecordHref({ lead_id: null, contact_id: ID })).toBe(`/contacts/${ID}`);
    expect(messageRecordHref({ lead_id: null, contact_id: null })).toBeNull();
  });

  it("explains failures in plain words, with a fallback", () => {
    expect(failureText("recipient_refused")).toMatch(/refused/);
    expect(failureText("something_new")).toBe("It could not be sent.");
    expect(failureText(null)).toBe("");
  });
});

describe("record pages", () => {
  it("builds the page of each record and refuses tampered ones", () => {
    expect(recordPath({ type: "lead", id: ID })).toBe(`/leads/${ID}`);
    expect(recordPath({ type: "opportunity", id: ID })).toBe(`/opportunities/${ID}`);
    expect(() => recordPath({ type: "lead", id: "../../users" })).toThrow();
    // @ts-expect-error - a type the browser could send but the app doesn't know
    expect(() => recordPath({ type: "tenant", id: ID })).toThrow();
  });
});

describe("form checks (mirror the backend)", () => {
  it("needs a subject and a text, within limits", () => {
    expect(checkMessage({ subject: " Hi ", body: "Text\n" })).toEqual({ ok: true, data: { subject: "Hi", body: "Text\n" } });
    expect(checkMessage({ subject: " ", body: "  " })).toEqual({
      ok: false, fieldErrors: { subject: "Enter a subject.", body: "Write the text of the e-mail." },
    });
    expect(checkMessage({ subject: "x".repeat(201), body: "x".repeat(50_001) })).toMatchObject({ ok: false });
  }); // prettier-ignore

  it.each([
    ["Hello {{recipient.first_name}}", []],
    ["{{ sender.name }}", []],
    ["{{recipient.salary}}", ["{{recipient.salary}}"]],
    ["{{a}} {{b}} {{a}}", ["{{a}}", "{{b}}"]],
    ["Hi {{recipient.first_name", ["'{{' without '}}'"]],
    ["Hi }}", ["'}}' without '{{'"]],
    ["{{}}", ["{{}}"]],
  ])("placeholders in %j", (text, problems) => {
    expect(placeholderProblems(text)).toEqual(problems);
  });

  it("refuses templates with unknown placeholders or missing fields", () => {
    expect(checkTemplate({ name: "First reply", subject: "Hi {{recipient.first_name}}", body: "Thanks" }).ok).toBe(true);
    const bad = checkTemplate({ name: " ", subject: "Hi {{recipient.age}}", body: "" });
    expect(bad).toEqual({
      ok: false,
      fieldErrors: {
        name: "Give the template a name.",
        subject: "Unknown or broken placeholders: {{recipient.age}}.",
        body: "Write the text of the template.",
      },
    });
  }); // prettier-ignore
});

describe("who can be written to", () => {
  it("needs an address; withdrawn consent stops sending but not logging", () => {
    expect(blockedReason({ email: "a@b.de" }, "send")).toBeNull();
    expect(blockedReason({ email: null }, "log")).toBe("no e-mail address");
    expect(blockedReason({ email: "not-an-address" }, "send")).toBe("no e-mail address");
    const withdrawn = { email: "a@b.de", email_consent: "withdrawn" as const };
    expect(blockedReason(withdrawn, "send")).toBe("asked not to receive e-mails");
    expect(blockedReason(withdrawn, "log")).toBeNull();
    expect(blockedReason({ email: "a@b.de", email_consent: "unknown" }, "send")).toBeNull();
  });

  it("lists an account's contacts with the reason they can't be chosen", () => {
    const contacts = [
      { id: "1", first_name: "Ada", last_name: "Lovelace", email: "ada@x.de", email_consent: "unknown" as const },
      { id: "2", first_name: null, last_name: "Noaddress", email: null, email_consent: "unknown" as const },
      { id: "3", first_name: "Bo", last_name: "Optout", email: "bo@x.de", email_consent: "withdrawn" as const },
    ];
    expect(recipientOptions(contacts, "send")).toEqual([
      { id: "1", label: "Ada Lovelace <ada@x.de>" },
      { id: "2", label: "Noaddress", blocked: "no e-mail address" },
      { id: "3", label: "Bo Optout", blocked: "asked not to receive e-mails" },
    ]);
    expect(recipientOptions(contacts, "log")[2]).toEqual({ id: "3", label: "Bo Optout <bo@x.de>" });
  }); // prettier-ignore
});

describe("permissions, menu and module tile (display only)", () => {
  const me = (...permissions: string[]): Me => ({
    user_id: "u", display_name: "T", email: null, tenant_id: "t", tenant_name: "Org",
    user_type: "staff", roles: [], permissions,
  }); // prettier-ignore
  const agent = me("communication:send", "communication:read:own");
  const manager = me("communication:send", "communication:read:all", "communication:template:manage");

  it("separates sending, reading and managing templates", () => {
    expect(canSendEmails(agent)).toBe(true);
    expect(canReadEmailCenter(agent)).toBe(true);
    expect(canManageEmailTemplates(agent)).toBe(false);
    expect(canManageEmailTemplates(manager)).toBe(true);
    expect(canReadEmailHistory(me("communication:send"))).toBe(true);
    expect(canReadEmailHistory(me("lead:read:all"))).toBe(false);
  });

  it("shows the E-mail menu entry only to people who may read e-mails", () => {
    expect(navigationFor(agent).map((i) => i.label)).toEqual(["Dashboard", "E-mail"]);
    expect(navigationFor(me("lead:read:own")).map((i) => i.label)).not.toContain("E-mail");
    expect(navigationFor({ permissions: ["communication:read:all"], user_type: "customer" })).toEqual([]);
  }); // prettier-ignore

  it("makes the Communication Center tile a link for readers only", () => {
    const tile = (m: Me) => modulesFor(m).find((x) => x.key === "communication");
    expect(tile(agent)).toMatchObject({ status: "available", link: "/communications" });
    expect(tile(me("lead:read:own"))?.link).toBeUndefined();
  });

  it("explains every communication permission on the profile page", () => {
    for (const p of ["communication:send", "communication:read:all", "communication:read:own", "communication:template:manage"])
      expect(PERMISSION_LABELS[p]).toBeTruthy();
  }); // prettier-ignore
});

describe("EmailStatusBadge", () => {
  it.each([
    ["queued", "Sending"],
    ["sent", "Sent"],
    ["failed", "Not delivered"],
    ["logged", "Received"],
  ] as const)("%s reads %s", (status, label) => {
    render(<EmailStatusBadge status={status} />);
    expect(screen.getByText(label)).toBeInTheDocument();
  });
});

describe("EmailComposer", () => {
  it("on a contact page names the person and never asks for an address", async () => {
    render(<EmailComposer mode="send" action={stub} fixedRecipient={{ contact_id: ID, label: "Ada <ada@x.de>" }} />);
    await userEvent.click(screen.getByRole("button", { name: "Send e-mail" }));
    const dialog = screen.getByRole("dialog", { name: "Send an e-mail" });
    expect(within(dialog).getByText("Ada <ada@x.de>")).toBeInTheDocument();
    expect(within(dialog).queryByRole("combobox", { name: "To" })).not.toBeInTheDocument();
    expect(dialog.querySelector('input[type="email"], input[name="to"]')).toBeNull();
  }); // prettier-ignore

  it("on an account page lists the contacts; blocked ones can't be chosen", async () => {
    const recipients = [
      { id: "1", label: "Ada <ada@x.de>" },
      { id: "2", label: "Bo", blocked: "asked not to receive e-mails" },
    ];
    render(<EmailComposer mode="send" action={stub} recipients={recipients} />);
    await userEvent.click(screen.getByRole("button", { name: "Send e-mail" }));
    const to = screen.getByRole("combobox", { name: "To" });
    expect(within(to).getByRole("option", { name: "Bo (asked not to receive e-mails)" })).toBeDisabled();
    expect(within(to).getByRole("option", { name: "Ada <ada@x.de>" })).toBeEnabled();
  }); // prettier-ignore

  it("fills subject and text from a template, and the text stays editable", async () => {
    const preview = vi.fn(async () => ({
      ok: true as const,
      preview: { subject: "Hi Ada", body: "Hello Ada,\nthanks.", missing: ["recipient.company"] },
    }));
    render(
      <EmailComposer mode="send" action={stub} fixedRecipient={{ contact_id: ID, label: "Ada" }}
        templates={[{ id: "t1", name: "First reply" }]} preview={preview} />,
    ); // prettier-ignore
    await userEvent.click(screen.getByRole("button", { name: "Send e-mail" }));
    await userEvent.selectOptions(screen.getByRole("combobox", { name: /Start from a template/ }), "t1");

    await waitFor(() => expect(screen.getByRole("textbox", { name: "Subject" })).toHaveValue("Hi Ada"));
    expect(preview).toHaveBeenCalledWith("t1", { lead_id: undefined, contact_id: ID });
    expect(screen.getByRole("textbox", { name: /Text/ })).toHaveValue("Hello Ada,\nthanks.");
    expect(screen.getByRole("status")).toHaveTextContent("recipient.company");
    const hidden = document.querySelector<HTMLInputElement>('input[name="template_id"]');
    expect(hidden?.value).toBe("t1");

    await userEvent.type(screen.getByRole("textbox", { name: "Subject" }), "!");
    expect(screen.getByRole("textbox", { name: "Subject" })).toHaveValue("Hi Ada!");
  }); // prettier-ignore

  it("asks for the contact first on an account page before using a template", async () => {
    const preview = vi.fn();
    render(
      <EmailComposer mode="send" action={stub} recipients={[{ id: "1", label: "Ada" }]}
        templates={[{ id: "t1", name: "First reply" }]} preview={preview} />,
    ); // prettier-ignore
    await userEvent.click(screen.getByRole("button", { name: "Send e-mail" }));
    await userEvent.selectOptions(screen.getByRole("combobox", { name: /Start from a template/ }), "t1");
    expect(screen.getByRole("alert")).toHaveTextContent("Choose who the e-mail is to first.");
    expect(preview).not.toHaveBeenCalled();
  });

  it("logging a received e-mail offers no templates and says nothing is sent", async () => {
    render(<EmailComposer mode="log" action={stub} fixedRecipient={{ lead_id: ID, label: "Lena" }} templates={[{ id: "t1", name: "x" }]} />);
    await userEvent.click(screen.getByRole("button", { name: "Log a received e-mail" }));
    const dialog = screen.getByRole("dialog", { name: "Log a received e-mail" });
    expect(within(dialog).getByText(/Nothing is sent/)).toBeInTheDocument();
    expect(within(dialog).queryByRole("combobox", { name: /template/ })).not.toBeInTheDocument();
    expect(within(dialog).getByText("From:")).toBeInTheDocument();
  }); // prettier-ignore

  it("shows the server's field errors and keeps what was typed", async () => {
    const failing = async () => ({ attempt: 1, fieldErrors: { subject: "Enter a subject." }, error: null });
    render(<EmailComposer mode="send" action={failing} fixedRecipient={{ contact_id: ID, label: "Ada" }} />);
    await userEvent.click(screen.getByRole("button", { name: "Send e-mail" }));
    await userEvent.type(screen.getByRole("textbox", { name: /Text/ }), "Keep me");
    await userEvent.click(screen.getByRole("button", { name: "Send" }));
    expect(await screen.findByText("Enter a subject.")).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: /Text/ })).toHaveValue("Keep me");
  }); // prettier-ignore
});
