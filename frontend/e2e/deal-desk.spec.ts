import { expect, test, type Browser, type Page } from "@playwright/test";

import { USERS, login, requireCredentials, uniqueName } from "./helpers";

/**
 * The deal desk (CRM-114, ADR 0024), end to end with the SCRIPTED model: it starts switched off
 * (the button says so), an administrator switches it on, a sales agent creates a deal with no
 * next step and a close date in the past and presses "Review this deal": three reviewers and a
 * desk lead answer, the review appears on the deal, and its suggested task waits for a manager -
 * nothing on the deal changed. A second review within the hour is refused. Creates clearly
 * fictional "E2eDealDesk…" records and leaves the deal desk switched off, as it starts.
 *
 * Needs the scripted model: CRM_AI_PROVIDER=fake for the API and E2E_FAKE_ASSISTANT=1 for this
 * run (the same switch as the other agent journeys). Without the switch the spec is skipped.
 */
test.beforeEach(() => {
  requireCredentials();
  test.skip(
    !process.env.E2E_FAKE_ASSISTANT,
    "E2E_FAKE_ASSISTANT is not set (scripted model switched off)",
  );
});

async function signedIn(browser: Browser, user: string, target = "/") {
  const page = await (await browser.newContext()).newPage();
  await login(page, user, target);
  return page;
}

async function switchDealDesk(page: Page, on: boolean) {
  await page.goto("/automation/agents");
  const box = page.getByRole("article", { name: "Deal desk" });
  const toggle = box.getByLabel("Switched on");
  if ((await toggle.isChecked()) !== on) {
    if (on) await toggle.check();
    else await toggle.uncheck();
    await box.getByRole("button", { name: "Save settings" }).click();
    await expect(page.getByText(/were saved/)).toBeVisible();
  }
}

/** A sales agent's own account and a deal on it whose close date has already passed. */
async function newDeal(page: Page) {
  const name = uniqueName("E2eDealDesk");
  await page.goto("/accounts/new");
  await page.getByLabel("Name").fill(`${name} account`);
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByText("The account was created.")).toBeVisible({
    timeout: 20_000,
  });
  const accountId = page.url().split("/accounts/")[1].split("?")[0];
  await page.goto(`/opportunities/new?account=${accountId}`);
  await page.getByLabel("Name").fill(name);
  await page.getByLabel(/Expected close/).fill("2026-01-15");
  await page.getByRole("button", { name: "Create opportunity" }).click();
  await expect(page.getByText("The opportunity was created.")).toBeVisible({
    timeout: 20_000,
  });
  return page.url().split("/opportunities/")[1].split("?")[0];
}

test("switched on, the deal desk reviews a deal and its task waits for a manager", async ({
  browser,
}) => {
  test.setTimeout(240_000);
  const admin = await signedIn(browser, USERS.admin);
  const agent = await signedIn(browser, USERS.agent1);
  try {
    await switchDealDesk(admin, false);
    const deal = await newDeal(agent);

    // 1. Off: the button is there, the API says it is switched off.
    const card = agent.getByRole("region", { name: "Deal desk" });
    await expect(card).toContainText("has not been reviewed yet");
    await card.getByRole("button", { name: "Review this deal" }).click();
    await expect(card.getByText(/switched off/)).toBeVisible();

    // 2. On: three reviewers and a desk lead answer; the review is on the deal.
    await switchDealDesk(admin, true);
    await agent.goto(`/opportunities/${deal}`);
    await card.getByRole("button", { name: "Review this deal" }).click();
    await expect(
      agent.getByText(/The deal desk reviewed this deal/),
    ).toBeVisible({
      timeout: 60_000,
    });
    await expect(card.getByText("Momentum")).toBeVisible();
    await expect(
      card.getByText(/expected close date 2026-01-15 has passed/),
    ).toBeVisible();
    await expect(card.getByText("Needs action").first()).toBeVisible();
    const task = card.getByRole("link", { name: "Suggested task 1" });
    await expect(task).toBeVisible();
    const proposal = (await task.getAttribute("href")) as string;
    expect(proposal).toMatch(/^\/approvals\/[0-9a-f-]{36}$/);

    // 3. A second review within the hour is refused, with the API's own sentence.
    await card.getByRole("button", { name: "Review this deal" }).click();
    await expect(card.getByText(/reviewed a moment ago/)).toBeVisible();

    // 4. A manager sees the suggested task waiting on this deal; nothing has been created yet.
    const manager = await signedIn(browser, USERS.manager, proposal);
    await expect(
      manager.getByText(/through the deal desk/).first(),
    ).toBeVisible();
    await expect(manager.getByText(/Plan a task: Follow up/)).toBeVisible();
    await expect(
      manager.getByRole("link", { name: /E2eDealDesk/ }).first(),
    ).toHaveAttribute("href", `/opportunities/${deal}`);
  } finally {
    await switchDealDesk(admin, false); // leave it as it starts
  }
});
