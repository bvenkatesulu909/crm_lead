import { expect, test, type Page } from "@playwright/test";

import { USERS, login, requireCredentials, uniqueName } from "./helpers";

/**
 * Workflow 3: customer account list, account details, employee profile - against the running
 * backend. Uses the fictional seed accounts (scripts/seed_dev_data.py) and creates "E2e…" data.
 */
test.beforeEach(() => requireCredentials());

// Fixed IDs of the seeded fictional accounts.
const ACCOUNT_A1 = "ac000000-0000-4000-8000-0000000000a1"; // owned by alpha.agent1
const ACCOUNT_A2 = "ac000000-0000-4000-8000-0000000000a2"; // owned by alpha.agent2

const nav = (page: Page) => page.getByRole("navigation", { name: "Main" });

test("a manager browses, searches and filters all accounts of the organisation", async ({
  page,
}) => {
  await login(page, USERS.manager);
  await nav(page).getByRole("link", { name: "Accounts" }).click();

  await expect(page.getByRole("heading", { name: "Accounts" })).toBeVisible();
  await expect(
    page.getByText("All customer accounts of your organisation."),
  ).toBeVisible();
  // Earlier E2E runs create many accounts; narrow the list to the demo customers.
  await page.goto("/accounts?q=example+customer");
  await expect(
    page.getByRole("link", { name: "Example Customer One Ltd" }),
  ).toBeVisible();
  await expect(
    page.getByRole("link", { name: "Example Customer Two Ltd" }),
  ).toBeVisible();
  await expect(page.getByText("Example Customer Three Ltd")).toHaveCount(0); // other tenant

  await page.getByLabel("Search").fill("customer two");
  await page.getByRole("button", { name: "Apply" }).click();
  await expect(page).toHaveURL(/q=customer\+two/);
  await expect(page.getByRole("row")).toHaveCount(2); // header + 1
  await expect(page.getByText("Showing 1–1 of 1")).toBeVisible();

  await page.getByLabel("Status").selectOption("inactive");
  await page.getByRole("button", { name: "Apply" }).click();
  await expect(page.getByText("No accounts match your search")).toBeVisible();
  await page.getByRole("link", { name: "Clear filters" }).click();
  await expect(page).toHaveURL("/accounts");

  await page.goto("/accounts?q=example+customer+one");
  await page.getByRole("link", { name: "Example Customer One Ltd" }).click();
  await expect(
    page.getByRole("heading", { level: 1, name: "Example Customer One Ltd" }),
  ).toBeVisible();
  await expect(page.getByText("Owner: Avery Agent")).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Converted leads" }),
  ).toBeVisible();
});

test("a sales agent sees only their own accounts - even by direct URL", async ({
  browser,
}) => {
  const agent = await (await browser.newContext()).newPage();
  await login(agent, USERS.agent1, "/accounts");
  await expect(agent.getByText("Customer accounts you own.")).toBeVisible();
  await agent.goto("/accounts?q=example+customer");
  await expect(
    agent.getByRole("link", { name: "Example Customer One Ltd" }),
  ).toBeVisible();
  await expect(agent.getByText("Example Customer Two Ltd")).toHaveCount(0);

  await agent.goto(`/accounts/${ACCOUNT_A2}`); // a colleague's account
  await expect(
    agent.getByRole("heading", { name: "Page not found" }),
  ).toBeVisible();

  const beta = await (await browser.newContext()).newPage();
  await login(beta, USERS.betaAdmin, `/accounts/${ACCOUNT_A1}`); // another tenant's account
  await expect(
    beta.getByRole("heading", { name: "Page not found" }),
  ).toBeVisible();
});

test("converting a lead creates an account whose history shows that lead", async ({
  page,
}) => {
  const lastName = uniqueName("E2eHistory");
  const company = `${lastName} Fictional Ltd`;
  await login(page, USERS.agent1, "/leads/new");
  await page.getByLabel(/Last name/).fill(lastName);
  await page.getByLabel(/Company/).fill(company);
  await page.getByRole("button", { name: "Create lead" }).click();
  await page.getByRole("link", { name: lastName }).click();

  const actions = page.getByRole("group", { name: "Lead actions" });
  await actions.getByRole("button", { name: "Qualify", exact: true }).click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Qualify lead" })
    .click();
  await expect(page.getByRole("status")).toHaveText("The lead was qualified.");
  await actions.getByRole("button", { name: "Convert" }).click();
  const convert = page.getByRole("dialog", { name: "Convert this lead" });
  await convert.getByLabel("Also create an opportunity").uncheck();
  await convert.getByRole("button", { name: "Convert lead" }).click();
  await expect(page.getByRole("status")).toHaveText("The lead was converted.");

  // From the lead to its new account, and back via the account's history.
  await page.getByRole("link", { name: company }).click();
  await expect(
    page.getByRole("heading", { level: 1, name: company }),
  ).toBeVisible();
  // The card (a <section>) that has the "Converted leads" heading.
  const history = page.locator("section").filter({
    has: page.getByRole("heading", { name: "Converted leads" }),
  });
  await expect(history.getByRole("link", { name: lastName })).toBeVisible();
  await expect(page.getByText("Owner: Avery Agent")).toBeVisible();

  // The new account is in the agent's list (they own it).
  await nav(page).getByRole("link", { name: "Accounts" }).click();
  await page.getByLabel("Search").fill(lastName);
  await page.getByRole("button", { name: "Apply" }).click();
  await expect(page.getByRole("link", { name: company })).toBeVisible();
});

test("support agents read all accounts but not lead history", async ({
  page,
}) => {
  await login(page, USERS.support, `/accounts/${ACCOUNT_A2}`);

  await expect(
    page.getByRole("heading", { level: 1, name: "Example Customer Two Ltd" }),
  ).toBeVisible();
  await expect(
    page.getByText("Lead history isn't part of your role."),
  ).toBeVisible();
});

test("customers cannot reach staff account screens", async ({ page }) => {
  await login(page, USERS.customer, "/accounts");

  await expect(page).toHaveURL("/portal");
  await expect(page.getByRole("table")).toHaveCount(0);
});

test("the employee profile shows identity, organisation, role and abilities", async ({
  page,
}) => {
  await login(page, USERS.agent1);
  await page.getByRole("button", { name: /account menu/i }).click();
  await page.getByRole("link", { name: "Your profile" }).click();

  await expect(
    page.getByRole("heading", { name: "Your profile" }),
  ).toBeVisible();
  const account = page.getByRole("heading", { name: "Account" }).locator("..");
  await expect(account).toContainText("Avery Agent");
  await expect(account).toContainText("agent1@alpha.example.test");
  await expect(account).toContainText("Alpha Demo (fictional)");
  await expect(account).toContainText("Sales Agent");
  await expect(account).toContainText("Convert qualified leads");
  await expect(account).not.toContainText("Assign leads to colleagues"); // managers only
  await expect(
    page.getByRole("link", { name: /Manage sign-in settings/ }),
  ).toHaveAttribute("href", "http://localhost:9080/realms/crm/account/");

  await page
    .getByRole("main")
    .getByRole("button", { name: "Sign out" })
    .click();
  await expect(page).toHaveURL(/\/login\?signed_out=1/);
});
