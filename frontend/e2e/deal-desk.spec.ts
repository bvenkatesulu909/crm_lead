import { expect, test, type Browser, type Page } from "@playwright/test";

import { USERS, login, requireCredentials, uniqueName } from "./helpers";

/**
 * The deal desk and account research (CRM-114, ADR 0024), end to end with the SCRIPTED model.
 *
 * Deal desk: switched off by an administrator, the button says so; switched on again, a sales
 * agent's deal with no next step and a close date in the past gets a review from three reviewers
 * and a desk lead, and its suggested task waits for a manager - nothing on the deal changed. A
 * second review within the hour is refused.
 *
 * Account research: switched on, a sales agent researches their own account; every sentence of
 * the brief comes from the CRM and the deal it names is linked.
 *
 * Creates clearly fictional "E2eDealDesk…" records and leaves both switches as they were (the deal
 * desk starts on for every organisation, account research off).
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

type Agent = "Deal desk" | "Account research";

/** Sets an agent's switch on the AI agents page and says how it was before. */
async function switchAgent(page: Page, agent: Agent, on: boolean) {
  await page.goto("/automation/agents");
  const box = page.getByRole("article", { name: agent });
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
  return {
    accountId,
    deal: page.url().split("/opportunities/")[1].split("?")[0],
    name,
  };
}

test("switched on, the deal desk reviews a deal and its task waits for a manager", async ({
  browser,
}) => {
  test.setTimeout(240_000);
  const admin = await signedIn(browser, USERS.admin);
  const agent = await signedIn(browser, USERS.agent1);
  const before = await switchAgent(admin, "Deal desk", false);
  try {
    const { deal } = await newDeal(agent);

    // 1. Off: the button is there, the API says it is switched off.
    const card = agent.getByRole("region", { name: "Deal desk" });
    await expect(card).toContainText("has not been reviewed yet");
    await card.getByRole("button", { name: "Review this deal" }).click();
    await expect(card.getByText(/switched off/)).toBeVisible();

    // 2. On: three reviewers and a desk lead answer; the review is on the deal.
    await switchAgent(admin, "Deal desk", true);
    await agent.goto(`/opportunities/${deal}`);
    await card.getByRole("button", { name: "Review this deal" }).click();
    await expect(
      agent.getByText(/The deal desk reviewed this deal/),
    ).toBeVisible({
      timeout: 60_000,
    });
    await expect(card.getByRole("heading", { name: "Momentum" })).toBeVisible();
    await expect(
      card.getByText(/expected close date 2026-01-15 has passed/).first(),
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
    await expect(
      manager.getByText(/Plan a task: Follow up/).first(),
    ).toBeVisible();
    await expect(
      manager.getByRole("link", { name: /E2eDealDesk/ }).first(),
    ).toHaveAttribute("href", `/opportunities/${deal}`);
  } finally {
    await switchAgent(admin, "Deal desk", before); // leave it as it was
  }
});

test("switched on, account research writes a brief whose sentences name their source", async ({
  browser,
}) => {
  test.setTimeout(180_000);
  const admin = await signedIn(browser, USERS.admin);
  const agent = await signedIn(browser, USERS.agent1);
  const before = await switchAgent(admin, "Account research", true);
  try {
    const { accountId, deal, name } = await newDeal(agent);
    await agent.goto(`/accounts/${accountId}`);
    const card = agent.getByRole("region", { name: "Account research" });
    await expect(card).toContainText("No brief has been written");
    await card.getByRole("button", { name: "Research this account" }).click();
    await expect(
      agent.getByText("The brief was written from this account's records."),
    ).toBeVisible({ timeout: 60_000 });
    await expect(card.getByText(/from the CRM's own records/)).toBeVisible();
    // The deal on the account is named, as data, and linked.
    await expect(
      card.getByText(new RegExp(`Open deal .*${name}`)),
    ).toBeVisible();
    await expect(
      card.getByRole("link", { name: "Open deal" }).first(),
    ).toHaveAttribute("href", `/opportunities/${deal}`);

    // A second brief within the hour is refused with the API's own sentence.
    await card.getByRole("button", { name: "Research this account" }).click();
    await expect(card.getByText(/researched a moment ago/)).toBeVisible();
  } finally {
    await switchAgent(admin, "Account research", before); // leave it as it was
  }
});
