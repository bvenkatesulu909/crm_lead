import { execFileSync } from "node:child_process";
import path from "node:path";

import { expect, test, type Browser, type Page } from "@playwright/test";

import {
  USERS,
  chooseAccount,
  login,
  requireCredentials,
  uniqueName,
} from "./helpers";
import { latestMessageTo } from "./mailpit";

/**
 * Communication Center (ADR 0012, docs/communications.md), end to end with a real Mailpit inbox.
 * A manager writes a template; the agent writes to their own contact starting from it; the
 * worker sends it; the reply is logged by hand; the Communication Center lists both. Other
 * people see only what they may. Creates clearly fictional "E2E…" records and *.example.test
 * addresses. alpha.agent1 owns "Example Customer One Ltd".
 */
test.beforeEach(() => requireCredentials());

async function signedIn(browser: Browser, user: string, target = "/") {
  const page = await (await browser.newContext()).newPage();
  await login(page, user, target);
  return page;
}

/** Runs the background worker once, like the "python -m app.worker" window would. */
function runWorkerOnce() {
  execFileSync(path.join("..", "backend", ".venv", "Scripts", "python.exe"), ["-m", "app.worker", "--once"], {
    cwd: path.join("..", "backend"),
    timeout: 60_000,
    stdio: "ignore",
  });
} // prettier-ignore

const emailCard = (page: Page) =>
  page.getByRole("region", { name: "E-mails" });

/** The manager creates a template (after the unknown-placeholder check) and returns its name. */
async function createTemplate(manager: Page) {
  const name = uniqueName("E2E template ");
  await manager.goto("/communications");
  await manager.getByRole("link", { name: "Templates" }).click();
  await manager.getByRole("link", { name: "New template" }).click();
  await manager.getByLabel("Name").fill(name);
  await manager.getByLabel("Subject").fill("Hello {{recipient.salary}}");
  await manager.getByLabel("Text").fill("Dear {{recipient.full_name}},\n\nthank you for writing to {{organisation.name}}.\n\n{{sender.name}}");
  await manager.getByRole("button", { name: "Create template" }).click();
  await expect(manager.getByText("Unknown or broken placeholders: {{recipient.salary}}.")).toBeVisible();
  await manager.getByLabel("Subject").fill("Hello {{recipient.first_name}}");
  await manager.getByRole("button", { name: "Create template" }).click();
  await expect(manager.getByText("The template was created.")).toBeVisible();
  await expect(manager.getByRole("link", { name })).toBeVisible();
  return name;
} // prettier-ignore

/** The agent creates a contact with a fictional address on their own customer. */
async function createContact(agent: Page) {
  const lastName = uniqueName("E2eMail");
  const address = `${lastName.toLowerCase()}@example.test`;
  await agent.goto("/contacts/new");
  await chooseAccount(agent, "Account (optional)", "Example Customer One Ltd");
  await agent.getByLabel(/First name/).fill("Ada");
  await agent.getByLabel(/Last name/).fill(lastName);
  await agent.getByLabel(/^E-mail/).fill(address);
  await agent.getByRole("button", { name: "Create contact" }).click();
  await expect(agent.getByText("The contact was created.")).toBeVisible();
  return { lastName, address, url: new URL(agent.url()).pathname };
}

test("an agent e-mails a contact from a template, the reply is logged, the list shows both", async ({
  browser,
}) => {
  test.setTimeout(180_000);
  const manager = await signedIn(browser, USERS.manager);
  const template = await createTemplate(manager);

  const agent = await signedIn(browser, USERS.agent1);
  const contact = await createContact(agent);

  // 1. Send, starting from the template: subject and text are filled in for this person.
  await emailCard(agent).getByRole("button", { name: "Send e-mail" }).click();
  const dialog = agent.getByRole("dialog", { name: "Send an e-mail" });
  await expect(dialog).toContainText(`Ada ${contact.lastName} <${contact.address}>`); // from the record
  await dialog.getByLabel(/Start from a template/).selectOption({ label: template });
  await expect(dialog.getByLabel("Subject")).toHaveValue("Hello Ada");
  await expect(dialog.getByLabel("Text")).toHaveValue(new RegExp(`^Dear Ada ${contact.lastName},`));
  await dialog.getByLabel("Text").press("End");
  await dialog.getByLabel("Text").pressSequentially("\nP.S. See you on Monday.");
  await dialog.getByRole("button", { name: "Send", exact: true }).click();
  await expect(agent.getByText("The e-mail is on its way.")).toBeVisible();
  await expect(emailCard(agent)).toContainText("Hello Ada");
  await expect(emailCard(agent)).toContainText("Sending");

  // 2. The worker sends it: the text arrives exactly as edited, and replies go to the agent.
  runWorkerOnce();
  const mail = await latestMessageTo(contact.address);
  expect(mail.Subject).toBe("Hello Ada");
  expect(mail.Text).toContain(`Dear Ada ${contact.lastName},`);
  expect(mail.Text).toContain("P.S. See you on Monday.");
  expect(mail.Text).not.toContain("{{");
  expect(mail.ReplyTo.map((r) => r.Address)).toEqual([expect.stringMatching(/@alpha\.example\.test$/)]);
  await agent.reload();
  await expect(emailCard(agent)).toContainText("Sent");

  // 3. The customer answers by e-mail; the agent pastes it in. Nothing is sent.
  await emailCard(agent).getByRole("button", { name: "Log a received e-mail" }).click();
  const log = agent.getByRole("dialog", { name: "Log a received e-mail" });
  await expect(log).toContainText("Nothing is sent.");
  await log.getByRole("button", { name: "Save" }).click();
  await expect(log.getByText("Enter a subject.")).toBeVisible();
  await log.getByLabel("Subject").fill("Re: Hello Ada");
  await log.getByLabel("Text").fill("Monday works for me.");
  await log.getByRole("button", { name: "Save" }).click();
  await expect(agent.getByText("The received e-mail was saved in the history.")).toBeVisible();
  const rows = emailCard(agent).getByRole("listitem");
  await expect(rows.first()).toContainText("Re: Hello Ada");
  await expect(rows.first()).toContainText("Received");
  await expect(rows.nth(1)).toContainText("Hello Ada");

  // 4. The Communication Center: the agent's own e-mails, with filters.
  await agent.getByRole("link", { name: "E-mail", exact: true }).click();
  await expect(agent.getByRole("heading", { name: "Communication Center" })).toBeVisible();
  await expect(agent.getByRole("link", { name: "Templates" })).toHaveCount(0); // managers only
  await agent.getByLabel("Search").fill("Hello Ada");
  await agent.getByLabel("Status").selectOption({ label: "Received" });
  await agent.getByRole("button", { name: "Apply" }).click();
  // Earlier runs leave e-mails with the same subject, so look only at this run's address.
  const mine = agent.getByRole("row").filter({ hasText: contact.address });
  await expect(mine).toHaveCount(1); // the received one; the sent one is filtered out
  await expect(mine).toContainText("Re: Hello Ada");
  await expect(mine).toContainText("Received");

  // 5. The manager sees every e-mail of the organisation, and the account page has the history.
  await manager.goto(`/communications?q=${encodeURIComponent("Hello Ada")}`);
  await expect(manager.getByRole("cell", { name: contact.address }).first()).toBeVisible();
  await manager.goto(contact.url);
  await manager.getByRole("link", { name: "Example Customer One Ltd" }).first().click();
  await expect(emailCard(manager)).toContainText("Re: Hello Ada");
}); // prettier-ignore

test("e-mails and templates stay with the people allowed to see them", async ({ browser }) => {
  test.setTimeout(150_000);
  const manager = await signedIn(browser, USERS.manager);
  const template = await createTemplate(manager);
  const agent = await signedIn(browser, USERS.agent1);
  const contact = await createContact(agent);

  // A colleague can't open agent1's contact, so can't see or write its e-mails.
  const other = await signedIn(browser, USERS.agent2, contact.url);
  await expect(other.getByRole("region", { name: "E-mails" })).toHaveCount(0);
  await other.goto("/communications/templates");
  await expect(other.getByText("You don't have access to this page")).toBeVisible();

  // A deactivated template disappears from the agent's choices.
  await manager.goto("/communications/templates");
  const row = manager.getByRole("listitem").filter({ hasText: template });
  await row.getByRole("button", { name: "Deactivate" }).click();
  await manager.getByRole("dialog", { name: `Deactivate ${template}?` }).getByRole("button", { name: "Deactivate" }).click();
  await expect(manager.getByText("The template was deactivated.")).toBeVisible();
  await agent.reload();
  await emailCard(agent).getByRole("button", { name: "Send e-mail" }).click();
  const options = agent.getByRole("dialog", { name: "Send an e-mail" }).getByLabel(/Start from a template/).locator("option");
  await expect(options.filter({ hasText: template })).toHaveCount(0);

  // A customer has no Communication Center at all.
  const customer = await signedIn(browser, USERS.customer, "/portal");
  await customer.goto("/communications");
  await expect(customer).not.toHaveURL(/\/communications$/);
}); // prettier-ignore
