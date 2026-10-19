import { execFileSync } from "node:child_process";
import path from "node:path";

import { expect, test, type Browser } from "@playwright/test";

import { USERS, login, requireCredentials, uniqueName } from "./helpers";
import { latestMessageTo } from "./mailpit";

/**
 * Phase 17a (ADR 0006): a quote that needs approval notifies the managers - in the CRM and by
 * e-mail (Mailpit) - after the background worker has run.
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

test("a quote waiting for approval notifies the manager in the CRM and by e-mail", async ({
  browser,
}) => {
  test.setTimeout(150_000);
  const title = uniqueName("E2E approval ");

  // The agent submits a quote with a big discount.
  const agent = await signedIn(browser, USERS.agent1, "/quotes/new");
  await agent.getByLabel("Title").fill(title);
  await agent.getByLabel("Account").selectOption({ label: "Example Customer One Ltd" });
  await agent.getByRole("button", { name: "Add line" }).click();
  await agent.getByLabel("Line 1 product").selectOption({ label: "WID-100 – Demo widget" });
  await agent.getByLabel("Line 1 discount").fill("40");
  await agent.getByRole("button", { name: "Create quote" }).click();
  await expect(agent.getByRole("status")).toHaveText("The quote was created.");
  await agent.getByRole("group", { name: "Quote actions" }).getByRole("button", { name: "Submit" }).click();
  await agent.getByRole("dialog", { name: /Submit this quote/ }).getByRole("button", { name: "Submit" }).click();
  await expect(agent.getByText("Waiting for approval").first()).toBeVisible();
  const quoteUrl = new URL(agent.url()).pathname;

  runWorkerOnce();

  // The manager sees it in the inbox (badge in the header) and opens it.
  const manager = await signedIn(browser, USERS.manager, "/");
  await expect(manager.getByRole("link", { name: /^Notifications: \d+ unread$/ })).toBeVisible();
  await manager.getByRole("link", { name: /^Notifications: / }).click();
  const item = manager.getByRole("list", { name: "Notifications" }).getByRole("button", { name: new RegExp(`Approval needed: QT-\\d+: ${title}`) });
  await expect(item).toBeVisible();
  await item.click();
  await expect(manager).toHaveURL(new RegExp(`${quoteUrl}$`));
  await manager.goto("/notifications");
  await expect(manager.getByRole("button", { name: new RegExp(title) })).not.toContainText("unread");

  // Approval requests come by e-mail by default.
  const mail = await latestMessageTo("manager@alpha.example.test");
  expect(mail.Subject).toContain(`Approval needed: QT-`);
  expect(mail.Subject).toContain(title);
  expect(mail.Text).toContain(`${quoteUrl}`);

  // The agent who submitted is not told about their own submission.
  await agent.goto("/notifications");
  await expect(agent.getByText(new RegExp(`Approval needed: .*${title}`))).toHaveCount(0);
}); // prettier-ignore

test("everyone chooses which notifications also come by e-mail", async ({ browser }) => {
  const agent = await signedIn(browser, USERS.agent1, "/notifications/settings");
  const box = agent.getByLabel("A lead was assigned to you");
  const before = await box.isChecked();
  try {
    await box.setChecked(!before);
    await agent.getByRole("button", { name: "Save" }).click();
    await expect(agent.getByRole("status")).toHaveText("Your e-mail settings were saved.");
    await expect(agent.getByLabel("A lead was assigned to you")).toBeChecked({ checked: !before });
  } finally {
    await agent.getByLabel("A lead was assigned to you").setChecked(before);
    await agent.getByRole("button", { name: "Save" }).click();
  }
}); // prettier-ignore
