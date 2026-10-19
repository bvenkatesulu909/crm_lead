import { execFileSync } from "node:child_process";
import path from "node:path";

import { expect, test, type Browser, type Page } from "@playwright/test";

import { USERS, login, requireCredentials, uniqueName } from "./helpers";

/**
 * Phase 17b (ADR 0006): a tenant admin builds a rule in the UI; the worker runs it when an agent
 * submits a quote with a big discount. The rule is deleted again at the end.
 */
test.beforeEach(() => requireCredentials());

async function signedIn(browser: Browser, user: string, target = "/") {
  const page = await (await browser.newContext()).newPage();
  await login(page, user, target);
  return page;
}

function runWorkerOnce() {
  execFileSync(path.join("..", "backend", ".venv", "Scripts", "python.exe"), ["-m", "app.worker", "--once"], {
    cwd: path.join("..", "backend"), timeout: 60_000, stdio: "ignore",
  });
} // prettier-ignore

async function submitQuote(page: Page, title: string, discount: string) {
  await page.goto("/quotes/new");
  await page.getByLabel("Title").fill(title);
  await page.getByLabel("Account").selectOption({ label: "Example Customer One Ltd" });
  await page.getByRole("button", { name: "Add line" }).click();
  await page.getByLabel("Line 1 product").selectOption({ label: "WID-100 – Demo widget" });
  await page.getByLabel("Line 1 discount").fill(discount);
  await page.getByRole("button", { name: "Create quote" }).click();
  await expect(page.getByRole("status")).toHaveText("The quote was created.");
  await page.getByRole("group", { name: "Quote actions" }).getByRole("button", { name: "Submit" }).click();
  await page.getByRole("dialog", { name: /Submit this quote/ }).getByRole("button", { name: "Submit" }).click();
  await expect(page.getByText("Waiting for approval").first()).toBeVisible();
} // prettier-ignore

test("an admin's rule creates a task when a quote has a big discount", async ({ browser }) => {
  test.setTimeout(180_000);
  const ruleName = uniqueName("E2E big discounts ");
  const big = uniqueName("E2E rule big ");
  const small = uniqueName("E2E rule small ");

  // Only admins see Automation.
  const agent = await signedIn(browser, USERS.agent1, "/automation");
  await expect(agent.getByText("You don't have access to this page")).toBeVisible();

  const admin = await signedIn(browser, USERS.admin, "/");
  await admin.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Automation" }).click();
  await admin.getByRole("link", { name: "New rule" }).click();
  await admin.getByLabel("Name").fill(ruleName);
  await admin.getByLabel("When…").selectOption({ label: "A quote needs approval" });
  await admin.getByRole("button", { name: "Add condition" }).click();
  await admin.getByLabel("Condition 1 field").selectOption({ label: "Largest line discount (%)" });
  await admin.getByLabel("Condition 1 comparison").selectOption({ label: "is more than" });
  await admin.getByLabel("Condition 1 value").fill("20");
  await admin.getByLabel("Action 1 task subject").fill("Check discount on {record}");
  await admin.getByRole("button", { name: "Create rule" }).click();
  await expect(admin.getByRole("status")).toContainText("The rule was created.");
  const card = admin.getByRole("listitem").filter({ hasText: ruleName });
  await expect(card).toContainText("Largest line discount (%) is more than 20");
  await expect(card).toContainText('Create task "Check discount on {record}" for the owner');

  try {
    await submitQuote(agent, big, "30");
    await submitQuote(agent, small, "15"); // needs approval, but below the rule's 20 %
    runWorkerOnce();

    await agent.goto("/tasks");
    // Anchored: the task's hidden "Mark as done"/"Cancel" dialogs repeat its subject.
    await expect(agent.getByText(new RegExp(`^Check discount on QT-\\d+: ${big}$`))).toBeVisible();
    await expect(agent.getByText(new RegExp(`^Check discount on QT-\\d+: ${small}$`))).toHaveCount(0);

    await admin.goto("/automation");
    const run = admin.getByRole("list", { name: "Run log" }).getByRole("listitem").filter({ hasText: big });
    await expect(run).toContainText(ruleName);
    await expect(run).toContainText("Done");
    await expect(run).toContainText("task created");
  } finally {
    await admin.goto("/automation");
    await admin.getByRole("link", { name: ruleName }).click();
    await admin.getByRole("button", { name: "Delete rule" }).click();
    await admin.getByRole("dialog", { name: `Delete "${ruleName}"?` }).getByRole("button", { name: "Delete" }).click();
    await expect(admin.getByRole("status")).toHaveText("The rule was deleted.");
  }
}); // prettier-ignore
