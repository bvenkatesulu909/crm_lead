import { readFile } from "node:fs/promises";

import { expect, test, type Browser, type Page } from "@playwright/test";

import { USERS, login, requireCredentials, uniqueName } from "./helpers";

/**
 * Phase 18: standard reports, the report builder and CSV downloads.
 * Creates a clearly fictional lead so the builder has something of ours to find.
 */
test.beforeEach(() => requireCredentials());

async function signedIn(browser: Browser, user: string, target = "/") {
  const page = await (await browser.newContext()).newPage();
  await login(page, user, target);
  return page;
}

async function downloadText(page: Page, link: ReturnType<Page["getByRole"]>) {
  const [file] = await Promise.all([page.waitForEvent("download"), link.click()]);
  return { name: file.suggestedFilename(), text: (await readFile(await file.path())).toString("utf-8") };
}

test("a manager reads a report and downloads it as CSV", async ({ browser }) => {
  const manager = await signedIn(browser, USERS.manager, "/");
  await manager.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Reports" }).click();
  await expect(manager.getByRole("heading", { name: "Reports", level: 1 })).toBeVisible();
  const tabs = manager.getByRole("navigation", { name: "Reports" });
  await expect(tabs.getByRole("link")).toHaveText([
    "Sales: win rate", "Leads: conversion", "Revenue & quotes", "Support: SLA & satisfaction",
  ]); // prettier-ignore

  await tabs.getByRole("link", { name: "Leads: conversion" }).click();
  await expect(manager.getByRole("region", { name: "Lead conversion by source" })).toBeVisible();
  // Managers may pick a sales rep; the period is a plain date range.
  await expect(manager.getByLabel("Sales rep")).toBeVisible();
  await manager.getByLabel("From", { exact: true }).fill("2025-01-01");
  await manager.getByLabel("To", { exact: true }).fill("2026-12-31");
  await manager.getByRole("button", { name: "Apply" }).click();
  await expect(manager.getByRole("region", { name: "Lead conversion by source" })).toContainText("Total");

  const file = await downloadText(manager, manager.getByRole("link", { name: "Download CSV" }));
  expect(file.name).toMatch(/^leads-2025-01-01-2026-12-31\.csv$/);
  expect(file.text.charCodeAt(0)).toBe(0xfeff); // BOM: Excel reads UTF-8
  expect(file.text).toContain("Source,Created,Converted,Unqualified,Still open,Conversion %");

  // An impossible period is explained, not a blank page.
  await manager.goto("/reports?report=leads&start=2026-05-01&end=2026-01-01");
  await expect(manager.getByRole("alert").filter({ hasText: "This report could not be shown" })).toContainText(
    "start date must be before the end date",
  );
}); // prettier-ignore

test("agents see their own figures and can't choose another rep", async ({ browser }) => {
  const agent = await signedIn(browser, USERS.agent1, "/reports");
  await expect(agent.getByLabel("Sales rep")).toHaveCount(0);
  const [manager] = await Promise.all([signedIn(browser, USERS.manager, "/reports")]);
  await expect(manager.getByLabel("Sales rep")).toBeVisible();
  // Asking for someone else's figures by hand is refused by the API.
  const other = await agent.request.get(`/reports/sales/csv?owner_id=${crypto.randomUUID()}`, { maxRedirects: 0 });
  expect(other.status()).toBe(307); // back to the report page with the filter; no file
  expect(other.headers()["content-type"] ?? "").not.toContain("text/csv");
}); // prettier-ignore

test("the report builder lists, filters and exports records", async ({ browser }) => {
  const lastName = uniqueName("E2eReport");
  const agent = await signedIn(browser, USERS.agent1, "/leads/new");
  await agent.getByLabel(/Last name/).fill(lastName);
  await agent.getByRole("button", { name: "Create lead" }).click();
  await expect(agent.getByText("The lead was created.")).toBeVisible();

  await agent.goto("/reports/builder");
  await agent.getByLabel("Records").selectOption({ label: "Leads" });
  await agent.getByRole("button", { name: "Apply" }).click();
  // Only chosen columns appear.
  const columns = agent.getByRole("group", { name: "Columns" });
  for (const box of await columns.getByRole("checkbox").all()) await box.uncheck();
  await columns.getByLabel("Last name").check();
  await columns.getByLabel("Status").check();
  await agent.getByRole("button", { name: "Apply" }).click();
  const preview = agent.getByRole("table", { name: "Leads" });
  await expect(preview.getByRole("columnheader")).toHaveText(["Last name", "Status"]);
  await expect(preview.getByRole("cell", { name: lastName })).toBeVisible();

  const file = await downloadText(agent, agent.getByRole("link", { name: "Download CSV" }));
  expect(file.name).toBe("leads-export.csv");
  expect(file.text).toContain("Last name,Status");
  expect(file.text).toContain(lastName);

  // Another agent can't see this lead in their own export.
  const other = await signedIn(browser, USERS.agent2, "/reports/builder");
  await other.getByLabel("Records").selectOption({ label: "Leads" });
  await other.getByRole("button", { name: "Apply" }).click();
  await expect(other.getByRole("cell", { name: lastName })).toHaveCount(0);
}); // prettier-ignore
