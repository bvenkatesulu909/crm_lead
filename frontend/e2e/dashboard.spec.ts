import { expect, test, type Page } from "@playwright/test";

import { USERS, login, requireCredentials, uniqueName } from "./helpers";

/**
 * Role dashboards against the running backend and database. Earlier E2E runs keep adding data,
 * so these tests compare figures before/after an action instead of expecting fixed numbers.
 */
test.beforeEach(() => requireCredentials());

const tile = (page: Page, label: string) =>
  page
    .locator("dt", { hasText: new RegExp(`^${label}$`) })
    .locator("xpath=following-sibling::dd[1]");

async function tileNumber(page: Page, label: string): Promise<number> {
  return Number.parseInt((await tile(page, label).innerText()).trim(), 10);
}

test("a sales rep sees their own figures, and a new lead is counted at once", async ({
  page,
}, testInfo) => {
  await login(page, USERS.agent1);
  const dashboard = page.getByTestId("dashboard-representative");
  await expect(dashboard).toBeVisible();
  // One view only: no view tabs, no rep filter, no team table, no business figures.
  await expect(
    page.getByRole("navigation", { name: "Dashboard view" }),
  ).toHaveCount(0);
  await expect(page.getByLabel("Sales rep")).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Sales team" })).toHaveCount(
    0,
  );
  await expect(page.getByRole("heading", { name: "Business" })).toHaveCount(0);
  for (const heading of [
    "Leads by status",
    "Open pipeline by stage (now)",
    "Pending follow-ups",
    "Recent customer activity",
  ]) {
    await expect(page.getByRole("heading", { name: heading })).toBeVisible();
  }
  await page.screenshot({
    path: testInfo.outputPath("rep.png"),
    fullPage: true,
  });

  const before = await tileNumber(page, "Leads created");
  const lastName = uniqueName("E2eDash");
  await page.goto("/leads/new");
  await page.getByLabel(/Last name/).fill(lastName);
  await page.getByRole("button", { name: "Create lead" }).click();
  await expect(page.getByText("The lead was created.")).toBeVisible();

  await page.goto("/");
  await expect.poll(() => tileNumber(page, "Leads created")).toBe(before + 1);
  // The creation shows up in the activity feed, linked to the lead.
  await expect(
    page.getByRole("link", { name: `Lead created: ${lastName}` }),
  ).toBeVisible();
  // The API refuses a rep filter for the own-sales view: a hand-made URL can't widen it.
  await page.goto("/?view=manager");
  await expect(
    page.getByText("Dashboard figures are unavailable"),
  ).toBeVisible();
});

test("a sales manager filters the team dashboard by period and sales rep", async ({
  page,
}, testInfo) => {
  await login(page, USERS.manager);
  await expect(page.getByTestId("dashboard-manager")).toBeVisible();
  const views = page.getByRole("navigation", { name: "Dashboard view" });
  await expect(
    views.getByRole("link", { name: "Sales manager" }),
  ).toHaveAttribute("aria-current", "page");
  await expect(views.getByRole("link", { name: "Executive" })).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Business" })).toHaveCount(0);

  const team = page.getByRole("table");
  await expect(
    team.getByRole("rowheader", { name: "Avery Agent" }),
  ).toBeVisible();
  await expect(
    team.getByRole("rowheader", { name: "Blake Agent" }),
  ).toBeVisible();
  await page.screenshot({
    path: testInfo.outputPath("manager.png"),
    fullPage: true,
  });

  // Period preset.
  await page.getByLabel("Period").selectOption("7d");
  await page.getByRole("button", { name: "Apply" }).click();
  await expect(page).toHaveURL(/range=7d/);
  await expect(page.getByLabel("Period")).toHaveValue("7d");

  // Custom dates.
  await page.getByLabel("Period").selectOption("custom");
  await page.getByLabel("From", { exact: true }).fill("2026-01-01");
  await page.getByLabel("To", { exact: true }).fill("2026-01-31");
  await page.getByRole("button", { name: "Apply" }).click();
  await expect(page).toHaveURL(/range=custom/);
  await expect(page.getByTestId("dashboard-period")).toHaveText(
    "1 Jan 2026 – 31 Jan 2026",
  );

  // Sales rep filter: the team table narrows to that person.
  await page.goto("/");
  await page.getByLabel("Sales rep").selectOption({ label: "Avery Agent" });
  await page.getByRole("button", { name: "Apply" }).click();
  await expect(page).toHaveURL(/rep=/);
  await expect(page.getByRole("table").getByRole("rowheader")).toHaveText([
    "Avery Agent",
  ]);

  // Clicking a name in the team table does the same.
  await page.getByRole("link", { name: "Reset" }).click();
  await page
    .getByRole("link", { name: "Show the dashboard for Blake Agent" })
    .click();
  await expect(page.getByRole("table").getByRole("rowheader")).toHaveText([
    "Blake Agent",
  ]);
  await expect(page.getByLabel("Sales rep")).toHaveValue(/.+/);

  // "My sales" shows only the manager's own records and drops the rep filter.
  await page.getByRole("link", { name: "My sales" }).click();
  await expect(page.getByTestId("dashboard-representative")).toBeVisible();
  await expect(page).not.toHaveURL(/rep=/);
});

test("a tenant admin gets the executive view with business figures", async ({
  page,
}, testInfo) => {
  await login(page, USERS.betaAdmin);
  await expect(page.getByTestId("dashboard-executive")).toBeVisible();
  const business = page.getByRole("region", { name: "Business" });
  for (const label of [
    "Invoiced",
    "Payments received",
    "Outstanding (now)",
    "Overdue (now)",
    "Orders confirmed",
    "Open tickets (now)",
  ]) {
    await expect(business.getByText(label, { exact: true })).toBeVisible();
  }
  await page.screenshot({
    path: testInfo.outputPath("executive.png"),
    fullPage: true,
  });

  await page.getByRole("link", { name: "Sales manager" }).click();
  await expect(page.getByTestId("dashboard-manager")).toBeVisible();
  await expect(page.getByRole("region", { name: "Business" })).toHaveCount(0);
});

test("support staff have no sales dashboard", async ({ page }) => {
  await login(page, USERS.support);
  await expect(page.getByTestId(/^dashboard-/)).toHaveCount(0);
  await expect(page.getByText("Nothing to show yet")).toBeVisible();
});
