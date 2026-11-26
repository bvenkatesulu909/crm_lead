import { execFileSync } from "node:child_process";
import path from "node:path";

import { expect, test, type Browser, type Page } from "@playwright/test";

import { USERS, login, requireCredentials, uniqueName } from "./helpers";

/**
 * Research many accounts at once (ADR 0042, step BR6), end to end with the SCRIPTED writer.
 *
 * An administrator switches on account research and batch account research. A manager creates two
 * fictional accounts, finds them on the Accounts list, ticks both and asks for research: the
 * confirmation shows the figures and nothing starts until "Start research". The batch page shows
 * it running; once the worker ran it is finished with both accounts researched, each linking to
 * its brief. A finished batch offers no stop and nothing to retry. A sales agent sees no research
 * boxes and cannot open the batch page. Both switches are put back as they were.
 *
 * Needs the scripted model (CRM_AI_PROVIDER=fake for the API and the worker, E2E_FAKE_ASSISTANT=1
 * here). Like the other journeys that run the worker itself it expects NO standing worker.
 */
test.beforeEach(() => {
  requireCredentials();
  test.skip(
    !process.env.E2E_FAKE_ASSISTANT,
    "E2E_FAKE_ASSISTANT is not set (scripted model switched off)",
  );
});

function runWorkerOnce() {
  execFileSync(
    path.join("..", "backend", ".venv", "Scripts", "python.exe"),
    ["-m", "app.worker", "--once"],
    { cwd: path.join("..", "backend"), timeout: 90_000, stdio: "ignore" },
  );
}

async function signedIn(browser: Browser, user: string, target = "/") {
  const page = await (await browser.newContext()).newPage();
  await login(page, user, target);
  return page;
}

type Agent = "Account research" | "Batch account research";

/** Sets an agent's switch on the AI agents page and says how it was before. */
async function switchAgent(page: Page, agent: Agent, on: boolean) {
  await page.goto("/automation/agents");
  const box = page.getByRole("article", { name: agent, exact: true });
  const toggle = box.getByLabel("Switched on");
  const was = await toggle.isChecked();
  if (was !== on) {
    if (on) await toggle.check();
    else await toggle.uncheck();
    await box.getByRole("button", { name: "Save settings" }).click();
    await expect(page.getByText(/were saved/)).toBeVisible();
  }
  return was;
}

async function newAccount(page: Page, name: string) {
  await page.goto("/accounts/new");
  await page.getByLabel("Name").fill(name);
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByText("The account was created.")).toBeVisible({
    timeout: 20_000,
  });
}

test("a manager researches two ticked accounts in one batch", async ({
  browser,
}) => {
  test.setTimeout(300_000);
  const admin = await signedIn(browser, USERS.admin);
  const research = await switchAgent(admin, "Account research", true);
  const batches = await switchAgent(admin, "Batch account research", true);
  try {
    const manager = await signedIn(browser, USERS.manager);
    const prefix = uniqueName("E2eBatch");
    await newAccount(manager, `${prefix} one`);
    await newAccount(manager, `${prefix} two`);

    // --- tick both on the list and ask --------------------------------------------------------
    await manager.goto(`/accounts?q=${encodeURIComponent(prefix)}`);
    await expect(manager.getByRole("row")).toHaveCount(3); // header + two accounts
    await manager.getByLabel("Tick every account on this page").check();
    const ask = manager.getByRole("button", {
      name: "Research ticked accounts",
    });
    await expect(async () => {
      await ask.click();
      await expect(manager.getByRole("dialog")).toBeVisible({
        timeout: 5_000,
      });
    }).toPass({ timeout: 60_000 });
    const dialog = manager.getByRole("dialog");
    await expect(dialog.getByText("Accounts in the batch")).toBeVisible();
    await expect(dialog).toContainText("2");

    // Cancelling the dialog starts nothing.
    await dialog.getByRole("button", { name: "Cancel" }).click();
    await expect(manager).toHaveURL(/\/accounts\?/);

    await ask.click();
    await manager
      .getByRole("dialog")
      .getByRole("button", { name: "Start research" })
      .click();
    await expect(manager).toHaveURL(/\/accounts\/batches\/[0-9a-f-]{36}/, {
      timeout: 30_000,
    });
    await expect(manager.getByText("The batch started.")).toBeVisible();
    await expect(manager.getByText("Running", { exact: true })).toBeVisible();
    const batchUrl = manager.url().split("?")[0];

    // --- the worker researches them one at a time ----------------------------------------------
    await expect(async () => {
      runWorkerOnce();
      await manager.goto(batchUrl);
      await expect(manager.getByText("Finished", { exact: true })).toBeVisible({
        timeout: 2_000,
      });
    }).toPass({ timeout: 180_000 });
    await expect(manager.getByText("2 of 2 accounts ended")).toBeVisible();
    await expect(manager.getByText("Researched")).toHaveCount(2);
    await expect(
      manager.getByRole("link", { name: `${prefix} one` }),
    ).toBeVisible();
    await expect(manager.getByRole("link", { name: "Read it" })).toHaveCount(2);
    // A finished batch: nothing to stop, nothing to try again.
    await expect(
      manager.getByRole("button", { name: "Stop the batch" }),
    ).toHaveCount(0);
    await expect(
      manager.getByRole("button", { name: "Try them again" }),
    ).toHaveCount(0);

    // It is on the list of batches.
    await manager.goto("/accounts/batches");
    await expect(manager.getByText("2 of 2 ended").first()).toBeVisible();

    // --- a sales agent has no research boxes and no batch page ----------------------------------
    const agent = await signedIn(browser, USERS.agent1, "/accounts");
    await expect(
      agent.getByRole("button", { name: "Research ticked accounts" }),
    ).toHaveCount(0);
    await expect(
      agent.getByLabel("Tick every account on this page"),
    ).toHaveCount(0);
    await agent.goto(batchUrl);
    await expect(
      agent.getByText("You don't have access to this page"),
    ).toBeVisible();
  } finally {
    await switchAgent(admin, "Batch account research", batches);
    await switchAgent(admin, "Account research", research);
  }
});
