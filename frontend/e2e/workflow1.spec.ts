import { expect, test } from "@playwright/test";

import {
  USERS,
  login,
  requireCredentials,
  signOut,
  uniqueName,
} from "./helpers";

/**
 * Workflow 1: login and session, dashboard, lead list, lead creation - against the running
 * backend. Creates a few clearly fictional "E2E…" leads in the local development database.
 */
test.beforeEach(() => requireCredentials());

test("anonymous visitors are sent to login and come back to the page they wanted", async ({
  page,
}) => {
  await login(page, USERS.agent1, "/leads?status=new");

  await expect(page).toHaveURL("/leads?status=new");
  await expect(page.getByRole("heading", { name: "Leads" })).toBeVisible();
  await expect(page.getByLabel("Status")).toHaveValue("new");
});

test("a sales agent creates a lead and finds it in the list", async ({
  page,
}) => {
  const lastName = uniqueName("E2eAgent");
  await login(page, USERS.agent1);

  // Dashboard and role-based navigation.
  await expect(
    page.getByRole("heading", { name: /Welcome back, Avery/ }),
  ).toBeVisible();
  const nav = page.getByRole("navigation", { name: "Main" });
  await expect(nav.getByRole("link")).toHaveText([
    "Dashboard",
    "Leads",
    "Accounts",
    "Contacts",
    "Pipeline",
    "Quotes",
    "Contracts",
    "Tasks",
    "E-mail",
    "Orders",
    "Invoices",
    "Support",
    "Products",
    "Knowledge",
    "AI Assistant",
    "Reports",
  ]);

  // The blue sidebar also lists every other CRM module, with its status.
  const allModules = page.getByRole("navigation", { name: "All CRM modules" });
  await expect(allModules).toContainText("Marketing");
  await expect(allModules).toContainText("Administration");
  await expect(allModules.getByLabel("Marketing: Planned · phase 16")).toBeVisible();

  // Module overview: only working modules are links.
  const modules = page.getByRole("region", { name: "CRM modules" });
  await expect(modules.getByRole("listitem")).toHaveCount(21);
  await expect(modules.getByRole("link")).toHaveText([
    /Lead Management/,
    /Customer Management/,
    /Contacts/,
    /Sales Opportunities/,
    /Activities/,
    /Product Catalog/,
    /Quotations/,
    /Contracts & Renewals/,
    /Orders/,
    /Invoices/,
    /Customer Support/,
    /Documents/,
    /Communication Center/,
    /Workflow & Notifications/,
    /Reports/,
    /AI Assistant/,
    /Knowledge Base/,
  ]);
  await expect(modules.getByText("AI Assistant").first()).toBeVisible();

  // Form validation before anything reaches the server.
  await page.getByRole("link", { name: "New lead" }).click();
  await page.getByRole("button", { name: "Create lead" }).click();
  await expect(page.getByText("Last name is required.")).toBeVisible();
  await expect(page.getByLabel(/Last name/)).toBeFocused();

  // Create for real.
  await page.getByLabel(/First name/).fill("Test");
  await page.getByLabel(/Last name/).fill(lastName);
  await page.getByLabel(/E-mail/).fill("e2e@E2E.Example.TEST");
  await page.getByLabel(/Company/).fill("E2E Fictional Ltd");
  await page.getByLabel(/Source/).selectOption("web");
  await page.getByRole("button", { name: "Create lead" }).click();

  await expect(page).toHaveURL(/\/leads\?created=/);
  await expect(page.getByRole("status")).toHaveText("The lead was created.");
  const row = page.getByRole("row", { name: new RegExp(lastName) });
  await expect(row).toContainText("e2e@e2e.example.test"); // domain normalised by the backend
  await expect(row).toContainText("New");

  // Search (case-insensitive) narrows the list to this lead.
  await page.getByLabel("Search").fill(lastName.toLowerCase());
  await page.getByRole("button", { name: "Apply" }).click();
  await expect(page.getByRole("row")).toHaveCount(2); // header + 1 lead
  await expect(page.getByText("Showing 1–1 of 1")).toBeVisible();
});

test("visibility of leads is decided by the backend: own, all, or other tenant", async ({
  browser,
}) => {
  const lastName = uniqueName("E2eScope");
  const agentPage = await (await browser.newContext()).newPage();
  await login(agentPage, USERS.agent1, "/leads/new");
  await agentPage.getByLabel(/Last name/).fill(lastName);
  await agentPage.getByRole("button", { name: "Create lead" }).click();
  await expect(agentPage).toHaveURL(/created=/);

  const search = async (username: string) => {
    const page = await (await browser.newContext()).newPage();
    await login(page, username, `/leads?q=${lastName}`);
    return page;
  };

  const manager = await search(USERS.manager); // sales manager: all leads of the tenant
  await expect(
    manager.getByRole("row", { name: new RegExp(lastName) }),
  ).toBeVisible();

  const colleague = await search(USERS.agent2); // other agent: not theirs
  await expect(colleague.getByText("No leads match your search")).toBeVisible();

  const otherTenant = await search(USERS.betaAdmin); // other tenant: never
  await expect(
    otherTenant.getByText("No leads match your search"),
  ).toBeVisible();
});

test("roles without lead access don't see it - and the backend refuses direct URLs", async ({
  page,
}) => {
  await login(page, USERS.support);

  const nav = page.getByRole("navigation", { name: "Main" });
  await expect(nav.getByRole("link")).toHaveText([
    "Dashboard",
    "Accounts",
    "Contacts",
    "Tasks",
    "E-mail",
    "Orders",
    "Invoices",
    "Support",
    "Products",
    "AI Assistant",
    "Reports",
  ]);
  await expect(page.getByRole("link", { name: "New lead" })).toHaveCount(0);
  // The module overview shows Lead Management, but not as a link for this role.
  const modules = page.getByRole("region", { name: "CRM modules" });
  await expect(modules.getByRole("link")).toHaveText([
    /Customer Management/,
    /Contacts/,
    /Activities/,
    /Product Catalog/,
    /Orders/,
    /Invoices/,
    /Customer Support/,
    /Documents/,
    /Communication Center/,
    /Workflow & Notifications/,
    /Reports/,
    /AI Assistant/,
  ]);
  await expect(
    modules.getByText("Not included in your role").first(),
  ).toBeVisible();

  // Typing the URL directly: the page asks the API, the API answers 403.
  await page.goto("/leads");
  await expect(
    page.getByText("You don't have access to this page"),
  ).toBeVisible();
  await page.goto("/leads/new");
  await expect(
    page.getByText("You don't have access to this page"),
  ).toBeVisible();
});

test("customers are kept out of the staff CRM", async ({ page }) => {
  await login(page, USERS.customer);

  // Customers land in their own portal, and staff URLs send them back there.
  await expect(page).toHaveURL("/portal");
  await page.goto("/leads");
  await expect(page).toHaveURL("/portal");
  await expect(page.getByRole("table")).toHaveCount(0);
});

test("tokens never reach browser JavaScript", async ({ page, context }) => {
  await login(page, USERS.agent1, "/leads");

  const session = (await context.cookies()).find(
    (c) => c.name === "crm_session",
  );
  expect(session?.httpOnly).toBe(true);
  expect(session?.sameSite).toBe("Lax");
  const storage = await page.evaluate(() => ({
    local: Object.keys(localStorage).length,
    session: Object.keys(sessionStorage).length,
    cookies: document.cookie,
  }));
  expect(storage).toEqual({ local: 0, session: 0, cookies: "" });
  // No JWT anywhere in the page the browser received.
  expect(await page.content()).not.toMatch(/eyJ[\w-]{10,}\.eyJ[\w-]{10,}/);
});

test("signing out ends the session in the app and in Keycloak", async ({
  page,
  context,
}) => {
  await login(page, USERS.agent1);
  await signOut(page);

  await expect(page.getByText("You have been signed out.")).toBeVisible();
  expect((await context.cookies()).some((c) => c.name === "crm_session")).toBe(
    false,
  );
  await page.goto("/leads");
  await expect(page).toHaveURL(/\/login\?returnTo=%2Fleads/);
  // Keycloak asks for the password again: its session really ended.
  await page.getByRole("link", { name: "Sign in" }).click();
  await expect(page.locator("#password")).toBeVisible();
});

test("keyboard users can skip straight to the content", async ({ page }) => {
  await login(page, USERS.agent1);

  await page.keyboard.press("Tab");
  await expect(
    page.getByRole("link", { name: "Skip to main content" }),
  ).toBeFocused();
});
