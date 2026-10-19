import { expect, test, type Browser, type Page } from "@playwright/test";

import { USERS, login, requireCredentials, uniqueName } from "./helpers";

/**
 * Phase B: accounts (create, edit, deactivate, archive, restore), contacts (primary contact,
 * consent, history) and logging activities on a lead - against the running backend.
 * Creates clearly fictional "E2e…" records.
 */
test.beforeEach(() => requireCredentials());

const nav = (page: Page) => page.getByRole("navigation", { name: "Main" });

async function signedIn(browser: Browser, user: string, target = "/") {
  const page = await (await browser.newContext()).newPage();
  await login(page, user, target);
  return page;
}

async function createAccount(page: Page, name: string) {
  await page.goto("/accounts/new");
  await page.getByLabel("Name").fill(name);
  await page.getByLabel(/Segment/).selectOption({ label: "Small business" });
  // A unique domain per test account: the same website would (rightly) trigger the
  // duplicate-customer warning against accounts from earlier runs.
  await page.getByLabel(/Website/).fill(`${name.toLowerCase()}.example.com`);
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByText("The account was created.")).toBeVisible();
  await expect(page.getByRole("heading", { level: 1, name })).toBeVisible();
  return page.url().split("/accounts/")[1].split("?")[0];
}

test("a sales rep builds a customer 360: account, primary contact, consent, timeline", async ({
  page,
}, testInfo) => {
  await login(page, USERS.agent1);
  await nav(page).getByRole("link", { name: "Contacts" }).click();
  await expect(page.getByRole("heading", { name: "Contacts" })).toBeVisible();

  const name = uniqueName("E2eAccount");
  await createAccount(page, name);
  await expect(page.getByText("Small business").first()).toBeVisible();
  await expect(
    page.getByRole("link", { name: /^https:\/\/e2eaccount.*\.example\.com$/ }),
  ).toBeVisible();

  // Add a primary contact from the account page.
  await page.getByRole("link", { name: "Add contact" }).click();
  await expect(page.getByLabel(/^Account/)).not.toHaveValue("");
  await page.getByLabel(/First name/).fill("Sam");
  // Unique per run: an identical name or e-mail would (rightly) raise the duplicate warning.
  const lastName = uniqueName("Sample");
  await page.getByLabel(/Last name/).fill(lastName);
  await page.getByLabel(/Designation/).fill("Head of IT");
  await page
    .getByLabel(/^E-mail/)
    .fill(`${lastName.toLowerCase()}@example.test`);
  await page.getByLabel("Primary contact of the account").check();
  await page.getByLabel("Marketing e-mail consent").selectOption("granted");
  await page.getByRole("button", { name: "Create contact" }).click();
  await expect(page.getByText("The contact was created.")).toBeVisible();
  await expect(page.getByText(/Agreed to e-mails \(since/)).toBeVisible();
  await expect(
    page.getByText("Primary contact", { exact: true }).first(),
  ).toBeVisible();

  // Edit: withdraw consent; the history shows old → new.
  await page.getByRole("link", { name: "Edit" }).click();
  await page.getByLabel("Marketing e-mail consent").selectOption("withdrawn");
  await page.getByLabel("Do not call this person").check();
  await page.getByRole("button", { name: "Save changes" }).click();
  await expect(page.getByText("Your changes were saved.")).toBeVisible();
  await expect(
    page.getByText("E-mail consent: Agreed to e-mails → Opted out of e-mails"),
  ).toBeVisible();
  await expect(page.getByText("Do not call: No → Yes")).toBeVisible();

  // Back on the account: contact card and relationship timeline.
  await page.getByRole("link", { name }).click();
  const contacts = page
    .getByRole("region", { name: /Contacts/ })
    .or(page.locator("section", { hasText: "Contacts (1)" }));
  await expect(
    contacts.getByRole("link", { name: `Sam ${lastName}` }),
  ).toBeVisible();
  await expect(contacts.getByText("Primary", { exact: true })).toBeVisible();
  await expect(page.getByText("Contact added").first()).toBeVisible();
  await expect(page.getByText("Primary contact changed")).toBeVisible();
  await expect(page.getByText("Account created")).toBeVisible();

  // Edit the account: the change shows in the timeline.
  await page.getByRole("link", { name: "Edit" }).click();
  await page.getByLabel(/Industry/).fill("Manufacturing");
  await page.getByRole("button", { name: "Save changes" }).click();
  await expect(page.getByText("Your changes were saved.")).toBeVisible();
  await expect(page.getByText("Industry: — → Manufacturing")).toBeVisible();
  await page.screenshot({
    path: testInfo.outputPath("account-360.png"),
    fullPage: true,
  });

  // Bad input is explained, not saved.
  await page.getByRole("link", { name: "Edit" }).click();
  await page.getByLabel(/Website/).fill("javascript:alert(1)");
  await page.getByRole("button", { name: "Save changes" }).click();
  await expect(
    page.getByText("Enter a web address such as https://example.com."),
  ).toBeVisible();
});

test("deactivate, archive and restore: agents deactivate, only managers archive", async ({
  browser,
}) => {
  const agent = await signedIn(browser, USERS.agent1);
  const name = uniqueName("E2eArchive");
  const id = await createAccount(agent, name);

  await agent.getByRole("button", { name: "Deactivate" }).click();
  await agent
    .getByRole("dialog")
    .getByLabel(/Reason/)
    .fill("No longer trading");
  await agent
    .getByRole("dialog")
    .getByRole("button", { name: "Deactivate" })
    .click();
  await expect(agent.getByText("The account is now inactive.")).toBeVisible();
  await expect(agent.getByRole("button", { name: "Reactivate" })).toBeVisible();
  await expect(agent.getByRole("button", { name: "Archive" })).toHaveCount(0); // agents can't
  await expect(agent.getByText("Reason: No longer trading")).toBeVisible();
  await agent.goto("/accounts?archived=1"); // and can't open the archive by URL either
  await expect(
    agent.getByText("You don't have access to this page"),
  ).toBeVisible();

  const manager = await signedIn(browser, USERS.manager, `/accounts/${id}`);
  await manager.getByRole("button", { name: "Archive" }).click();
  const dialog = manager.getByRole("dialog");
  await dialog.getByRole("button", { name: "Archive account" }).click();
  await expect(
    dialog.getByText("Please say why the account is archived."),
  ).toBeVisible();
  await dialog.getByLabel("Reason").fill("Company closed");
  await dialog.getByRole("button", { name: "Archive account" }).click();
  await expect(manager.getByText(/The account was archived/)).toBeVisible();

  await manager.getByRole("link", { name: "Archived" }).click();
  await expect(manager).toHaveURL(/archived=1/);
  await manager.getByLabel("Search").fill(name);
  await manager.getByRole("button", { name: "Apply" }).click();
  await manager.getByRole("button", { name: "Restore" }).click();
  await manager
    .getByRole("dialog")
    .getByRole("button", { name: "Restore account" })
    .click();
  await expect(
    manager.getByText("The account was restored from the archive."),
  ).toBeVisible();
  await expect(manager.getByText("Account archived")).toBeVisible();
  await expect(manager.getByText("Reason: Company closed")).toBeVisible();
});

test("colleagues and other organisations can't open someone else's contact", async ({
  browser,
}) => {
  const agent1 = await signedIn(browser, USERS.agent1, "/contacts/new");
  await agent1.getByLabel(/Last name/).fill(uniqueName("E2ePrivate"));
  await agent1.getByRole("button", { name: "Create contact" }).click();
  await expect(agent1.getByText("The contact was created.")).toBeVisible();
  const url = new URL(agent1.url()).pathname;

  for (const user of [USERS.agent2, USERS.betaAdmin]) {
    const other = await signedIn(browser, user, url);
    await expect(
      other.getByRole("heading", { name: "Page not found" }),
    ).toBeVisible();
  }

  // Support staff read contacts but can't create or change them.
  const support = await signedIn(browser, USERS.support, url);
  await expect(support.getByRole("heading", { level: 1 })).toBeVisible();
  await expect(support.getByRole("link", { name: "Edit" })).toHaveCount(0);
  await support.goto("/contacts");
  await expect(support.getByRole("link", { name: "New contact" })).toHaveCount(
    0,
  );
});

test("a sales rep logs a call on a lead and sees it in the timeline", async ({
  page,
}) => {
  await login(page, USERS.agent1, "/leads/new");
  const lastName = uniqueName("E2eLog");
  await page.getByLabel(/Last name/).fill(lastName);
  await page.getByRole("button", { name: "Create lead" }).click();
  await expect(page.getByText("The lead was created.")).toBeVisible();
  await page.getByRole("link", { name: lastName }).click();

  // The lead's own call/meeting log (the task panel below has similar fields).
  const log = page
    .locator("form")
    .filter({ has: page.locator("#activity-kind") });
  await log.getByRole("button", { name: "Log activity" }).click();
  await expect(page.getByText("Please add a short subject.")).toBeVisible();
  const logAgain = page
    .locator("form")
    .filter({ has: page.locator("#activity-kind") });
  await logAgain.getByLabel("Type").selectOption("call");
  await logAgain
    .getByLabel("Subject")
    .fill("Discussed pricing for 50 licences");
  await logAgain.getByLabel(/Notes/).fill("Wants a quote by Friday.");
  await logAgain.getByRole("button", { name: "Log activity" }).click();
  await expect(
    page.getByText("The activity was added to the timeline."),
  ).toBeVisible();
  await expect(
    page.getByText("Discussed pricing for 50 licences", { exact: true }),
  ).toBeVisible();
  await expect(page.getByText("Wants a quote by Friday.")).toBeVisible();
});
