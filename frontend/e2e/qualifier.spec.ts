import { expect, test, type Browser, type Page } from "@playwright/test";

import { USERS, login, requireCredentials, uniqueName } from "./helpers";

/**
 * The Qualifier (BP-03, docs/qualifier.md), end to end with the SCRIPTED model: an administrator
 * writes the procedure, a sales agent presses "Qualify" on a lead, the Qualifier only SUGGESTS
 * (a proposal waits in the approval queue), the agent can't approve their own request, a manager
 * can, and only then does the lead change. Creates clearly fictional "E2eQualify…" leads.
 *
 * Needs the scripted model: CRM_AI_PROVIDER=fake in backend/.env and E2E_FAKE_ASSISTANT=1 in
 * frontend/.env.local (the same switch as the approvals journey). The scripted Qualifier
 * qualifies a lead whose minimum budget is at least 80 lakh and has a phone number. Without the
 * switch the spec is skipped.
 */
test.beforeEach(() => {
  requireCredentials();
  test.skip(
    !process.env.E2E_FAKE_ASSISTANT,
    "E2E_FAKE_ASSISTANT is not set in .env.local (scripted model switched off)",
  );
});

async function signedIn(
  browser: Browser,
  user: string,
  target = "/",
): Promise<Page> {
  const page = await (await browser.newContext()).newPage();
  await login(page, user, target);
  return page;
}

/** An agent creates a lead that the scripted Qualifier will qualify. */
async function newRichLead(page: Page, prefix: string) {
  const lastName = uniqueName(prefix);
  await page.goto("/leads/new");
  await page.getByLabel(/Last name/).fill(lastName);
  await page.getByLabel(/Phone/).fill("+91 90000 00000"); // fictional
  await page.getByLabel(/Property type/).selectOption({ label: "Apartment" });
  await page.getByLabel(/Minimum budget/).fill("1 Cr");
  await page.getByLabel(/Maximum budget/).fill("1.5 Cr");
  await page.getByRole("button", { name: "Create lead" }).click();
  await page
    .getByRole("link", { name: new RegExp(lastName) })
    .first()
    .click();
  await page.waitForURL(/\/leads\/[0-9a-f-]{36}$/);
  return { lastName, id: page.url().split("/").pop() as string };
}

test("an administrator writes the procedure, the Qualifier suggests, a manager decides", async ({
  browser,
}) => {
  test.setTimeout(240_000);
  const agent = await signedIn(browser, USERS.agent1, "/leads/new");
  const lead = await newRichLead(agent, "E2eQualify");

  // 1. An administrator writes the procedure (a new version each run) and tries it on the lead.
  const admin = await signedIn(browser, USERS.admin, "/automation/qualifier");
  await admin.getByLabel("Name", { exact: true }).fill("E2e procedure");
  await admin
    .getByLabel("Steps")
    .fill(
      "The lead has a phone number.\nThe budget is stated and fits the property.",
    );
  await admin.getByRole("button", { name: "Save as a new version" }).click();
  await expect(
    admin.getByText("The procedure was saved as a new version."),
  ).toBeVisible();
  await expect(admin.getByText("The budget is stated and fits")).toBeVisible();

  const trial = admin.getByRole("form", { name: "Try the procedure" });
  await trial.getByLabel("Lead").selectOption({ label: lead.lastName });
  await trial.getByRole("button", { name: "Try it" }).click();
  await expect(trial).toContainText("Qualify the lead");

  // 2. The agent presses "Qualify": a proposal waits, the lead has NOT changed.
  await agent.goto(`/leads/${lead.id}`);
  const card = agent.getByRole("region", { name: "Qualifier" });
  await expect(card).toContainText("This lead has not been assessed yet.");
  await card.getByRole("button", { name: "Qualify", exact: true }).click();
  await expect(card).toContainText("Qualify the lead");
  await expect(card).toContainText("A proposal is waiting for approval.");
  await expect(agent.getByText("New", { exact: true }).first()).toBeVisible();

  // 3. A second press within the hour is refused in plain words.
  await card.getByRole("button", { name: "Qualify", exact: true }).click();
  await expect(agent.getByText(/assessed a moment ago/)).toBeVisible();

  // 4. The agent can't decide on their own request; the card names the Qualifier.
  await card.getByRole("link", { name: "Open the proposal" }).click();
  await agent.waitForURL(/\/approvals\/[0-9a-f-]{36}$/);
  await expect(agent.getByText(/through the Qualifier/)).toBeVisible();
  await expect(
    agent.getByText("You asked for this, so someone else has to decide on it."),
  ).toBeVisible();
  await expect(
    agent.getByRole("button", { name: "Approve", exact: true }),
  ).toHaveCount(0);

  // 5. A manager approves it; only now does the lead change.
  const manager = await signedIn(browser, USERS.manager, "/approvals");
  const waiting = manager
    .getByRole("article")
    .filter({ hasText: lead.lastName });
  await expect(waiting).toContainText("Qualifier");
  await waiting.getByRole("button", { name: "Approve", exact: true }).click();
  await waiting.getByRole("button", { name: "Approve and run" }).click();
  await expect(manager.getByText("The proposal was approved.")).toBeVisible();
  await manager.goto(`/leads/${lead.id}`);
  await expect(
    manager.getByText("Qualified", { exact: true }).first(),
  ).toBeVisible();
});

test("only an administrator can write the procedure; a support agent has no Qualifier", async ({
  browser,
}) => {
  const manager = await signedIn(browser, USERS.manager, "/automation/qualifier");
  await expect(
    manager.getByText("Only a tenant administrator can write the procedure."),
  ).toBeVisible();
  await expect(
    manager.getByRole("button", { name: "Save as a new version" }),
  ).toHaveCount(0);

  const support = await signedIn(browser, USERS.support, "/automation/qualifier");
  await expect(
    support.getByText("You don't have access to this page"),
  ).toBeVisible();
}); // prettier-ignore
