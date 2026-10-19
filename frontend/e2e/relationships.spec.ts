import { expect, test, type Browser, type Page } from "@playwright/test";

import { USERS, login, requireCredentials, uniqueName } from "./helpers";

/**
 * Phase B2: duplicate warnings, relationship transfer, customer health, lead scoring and
 * customer feedback (complaint + satisfaction rating) - against the running backend.
 */
test.beforeEach(() => requireCredentials());

async function signedIn(browser: Browser, user: string, target = "/") {
  const page = await (await browser.newContext()).newPage();
  await login(page, user, target);
  return page;
}

async function newAccount(
  page: Page,
  name: string,
  extra?: (p: Page) => Promise<void>,
) {
  await page.goto("/accounts/new");
  await page.getByLabel("Name").fill(name);
  if (extra) await extra(page);
  await page.getByRole("button", { name: "Create account" }).click();
}

const ticketActions = (page: Page) =>
  page.getByRole("group", { name: "Ticket actions" });

test("creating a likely duplicate customer asks first", async ({ page }) => {
  await login(page, USERS.agent1);
  const name = uniqueName("E2eDupe");
  await newAccount(page, `${name} Ltd`, async (p) => {
    await p.getByLabel(/Country/).fill("IN");
    await p.getByLabel(/Lifecycle stage/).selectOption("onboarding");
    await p.getByLabel(/Preferred language/).selectOption("te");
  });
  await expect(page.getByText("The account was created.")).toBeVisible();
  await expect(page.getByText("Onboarding").first()).toBeVisible();
  await expect(page.getByText("Telugu", { exact: true })).toBeVisible();

  // Same company, different legal form: the form warns and links to the existing one.
  await newAccount(page, `${name} Limited`);
  const warning = page
    .getByRole("alert")
    .filter({ hasText: "may be an existing customer" });
  await expect(warning).toBeVisible();
  await expect(
    warning.getByRole("link", { name: `${name} Ltd` }),
  ).toBeVisible();
  await expect(warning).toContainText("Same company name");
  await page.getByLabel(/This is a different customer/).check();
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByText("The account was created.")).toBeVisible();
});

test("a manager transfers a customer with its open work", async ({
  browser,
}) => {
  const agent = await signedIn(browser, USERS.agent1);
  const name = uniqueName("E2eTransfer");
  await newAccount(agent, name);
  await expect(agent.getByText("The account was created.")).toBeVisible();
  const url = new URL(agent.url()).pathname;

  const manager = await signedIn(browser, USERS.manager, url);
  await manager.getByRole("button", { name: "Transfer customer" }).click();
  const dialog = manager.getByRole("dialog");
  await dialog.getByRole("button", { name: "Transfer" }).click();
  await expect(dialog.getByText("Choose the new owner.")).toBeVisible();
  await dialog.getByLabel("New owner").selectOption({ label: "Blake Agent" });
  await dialog.getByLabel("Reason").fill("Territory change");
  await dialog.getByRole("button", { name: "Transfer" }).click();
  await expect(
    manager.getByText("The customer was transferred to the new owner."),
  ).toBeVisible();
  await expect(manager.getByText("Owner: Blake Agent")).toBeVisible();
  await expect(
    manager.getByText("Relationship owner transferred").first(),
  ).toBeVisible();
  await expect(manager.getByText("Reason: Territory change")).toBeVisible();

  await agent.goto(url);
  await expect(
    agent.getByRole("heading", { name: "Page not found" }),
  ).toBeVisible();
  // Agents never see the transfer button.
  const blake = await signedIn(browser, USERS.agent2, url);
  await expect(
    blake.getByRole("button", { name: "Transfer customer" }),
  ).toHaveCount(0);
});

test("customer health explains itself", async ({ page }) => {
  await login(page, USERS.agent1);
  const name = uniqueName("E2eHealth");
  await newAccount(page, name);
  await expect(
    page.getByRole("heading", { name: "Customer health" }),
  ).toBeVisible();
  await expect(page.getByText("No interaction recorded yet")).toBeVisible();
  await expect(page.getByText("No recorded interaction yet")).toBeVisible();

  await page.goto("/accounts/health");
  const row = page.getByRole("row").filter({ hasText: name });
  await expect(row).toContainText("Healthy · 80");
  await expect(row).toContainText("Inactive");
});

test("leads are scored with visible reasons", async ({ page }) => {
  await login(page, USERS.agent1, "/leads/new");
  const lastName = uniqueName("E2eScore");
  await page.getByLabel(/Last name/).fill(lastName);
  await page.getByLabel(/E-mail/).fill("score@e2e.example.test");
  await page.getByLabel(/Phone/).fill("+44 20 7946 0099");
  await page.getByLabel(/Company/).fill("E2E Scoring Ltd");
  await page.getByLabel(/Job title/).fill("Head of Purchasing");
  await page.getByLabel(/Source/).selectOption("referral");
  await page.getByRole("button", { name: "Create lead" }).click();
  await expect(page.getByText("The lead was created.")).toBeVisible();

  // 15 e-mail + 10 phone + 10 company + 15 senior title + 20 referral = 70 -> hot.
  await page.goto(`/leads?q=${lastName}&priority=hot`);
  const row = page.getByRole("row").filter({ hasText: lastName });
  await expect(row.getByText("Hot · 70")).toBeVisible();
  await row.getByRole("link", { name: lastName }).click();
  await expect(page.getByRole("heading", { name: "Lead score" })).toBeVisible();
  await expect(page.getByText("Senior decision-maker")).toBeVisible();
  await expect(page.getByText("Source: referral")).toBeVisible();
});

test("a customer complains, support resolves, the customer rates it", async ({
  browser,
}) => {
  const customer = await signedIn(
    browser,
    USERS.customer,
    "/portal/tickets/new",
  );
  const subject = uniqueName("E2eComplaint");
  await customer.getByLabel("What is it about?").selectOption("complaint");
  await customer.getByLabel("Subject").fill(subject);
  await customer
    .getByLabel("Description")
    .fill("The delivery arrived damaged.");
  await customer.getByRole("button", { name: "Submit ticket" }).click();
  await expect(customer.getByRole("status")).toContainText(
    "Your ticket was submitted",
  );
  await expect(customer.getByText(/Complaint · opened/)).toBeVisible();
  await expect(customer.getByText("How did we do?")).toHaveCount(0); // not resolved yet
  const ticketId = new URL(customer.url()).pathname.split("/").pop() ?? "";

  const support = await signedIn(
    browser,
    USERS.support,
    `/tickets?category=complaint&q=${subject}`,
  );
  await expect(
    support.getByRole("link", { name: new RegExp(subject) }),
  ).toBeVisible();
  await support.goto(`/tickets/${ticketId}`);
  await ticketActions(support).getByRole("button", { name: "Resolve" }).click();
  await support
    .getByRole("dialog")
    .getByRole("button", { name: "Resolve" })
    .click();
  await expect(support.getByText("SLA met")).toBeVisible();

  await customer.reload();
  await customer.getByRole("button", { name: "Send rating" }).click();
  await expect(customer.getByText("Choose 1 to 5 stars.")).toBeVisible();
  await customer.getByTitle("Happy", { exact: true }).click();
  await customer
    .getByLabel(/Anything you'd like to add/)
    .fill("Sorted quickly, thanks.");
  await customer.getByRole("button", { name: "Send rating" }).click();
  await expect(
    customer.getByText("Thank you for your feedback!"),
  ).toBeVisible();
  await expect(customer.getByText("Your rating:")).toBeVisible();

  await support.reload();
  await expect(support.getByLabel("4 of 5")).toBeVisible();
  await expect(support.getByText("“Sorted quickly, thanks.”")).toBeVisible();
});
