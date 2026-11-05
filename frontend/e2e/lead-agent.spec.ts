import { expect, test, type Browser, type Page } from "@playwright/test";

import { USERS, login, requireCredentials, uniqueName } from "./helpers";

/**
 * The lead agent (CRM-114, ADR 0022, docs/lead-agent.md), end to end with the SCRIPTED model: an
 * administrator switches it on, a sales agent presses "Ask the lead agent" on a new lead, the agent
 * only SUGGESTS (a proposal waits), a second ask within the hour is refused, a manager approves and
 * only then does the lead change; switched off again, the button says so. Creates clearly
 * fictional "E2eLeadAgent…" leads and leaves the agent switched off, as it starts.
 *
 * Needs the scripted model: CRM_AI_PROVIDER=fake for the API and E2E_FAKE_ASSISTANT=1 for this
 * run (the same switch as the approvals and Qualifier journeys). The scripted lead agent suggests
 * "contacted" for a new lead with a phone number. Without the switch the spec is skipped.
 */
test.beforeEach(() => {
  requireCredentials();
  test.skip(
    !process.env.E2E_FAKE_ASSISTANT,
    "E2E_FAKE_ASSISTANT is not set (scripted model switched off)",
  );
});

async function signedIn(
  browser: Browser,
  user: string,
  target = "/",
): Promise<Page> {
  const page = await (await browser.newContext()).newPage();
  await login(page, user, target);
  return page;
}

async function switchLeadAgent(page: Page, on: boolean) {
  await page.goto("/automation/agents");
  const box = page.getByRole("article", { name: "Lead agent" });
  const toggle = box.getByLabel("Switched on");
  if ((await toggle.isChecked()) !== on) {
    if (on) await toggle.check();
    else await toggle.uncheck();
    await box.getByRole("button", { name: "Save settings" }).click();
    await expect(page.getByText(/were saved/)).toBeVisible();
  }
}

/** A sales agent creates a new lead with a phone number: the scripted agent suggests a call. */
async function newLead(page: Page) {
  const lastName = uniqueName("E2eLeadAgent");
  await page.goto("/leads/new");
  await page.getByLabel(/Last name/).fill(lastName);
  await page.getByLabel(/Phone/).fill("+91 90000 00000"); // fictional
  await page.getByRole("button", { name: "Create lead" }).click();
  await page
    .getByRole("link", { name: new RegExp(lastName) })
    .first()
    .click();
  await page.waitForURL(/\/leads\/[0-9a-f-]{36}$/);
  return { lastName, id: page.url().split("/").pop() as string };
}

test("an admin switches it on, the lead agent suggests, a manager decides", async ({
  browser,
}) => {
  test.setTimeout(240_000);
  const admin = await signedIn(browser, USERS.admin, "/automation/agents");
  await switchLeadAgent(admin, true);
  try {
    const agent = await signedIn(browser, USERS.agent1, "/leads/new");
    const lead = await newLead(agent);

    // 1. The agent asks: a suggestion waits, the lead has NOT changed.
    const card = agent.getByRole("region", { name: "Lead agent" });
    await card.getByRole("button", { name: "Ask the lead agent" }).click();
    await expect(
      agent.getByText(/The lead agent made a suggestion\. It is waiting/),
    ).toBeVisible();
    await expect(agent.getByText("New", { exact: true }).first()).toBeVisible();

    // 2. A second ask within the hour is refused in plain words.
    await agent
      .getByRole("region", { name: "Lead agent" })
      .getByRole("button", { name: "Ask the lead agent" })
      .click();
    await expect(agent.getByText(/looked at a moment ago/)).toBeVisible();

    // 3. A manager approves it; only now does the lead change.
    const manager = await signedIn(browser, USERS.manager, "/approvals");
    const waiting = manager
      .getByRole("article")
      .filter({ hasText: lead.lastName });
    await expect(waiting).toContainText("lead agent");
    await waiting.getByRole("button", { name: "Approve", exact: true }).click();
    await waiting.getByRole("button", { name: "Approve and run" }).click();
    await expect(manager.getByText("The proposal was approved.")).toBeVisible();
    await manager.goto(`/leads/${lead.id}`);
    await expect(
      manager.getByText("Contacted", { exact: true }).first(),
    ).toBeVisible();

    // 4. Switched off again, the button says so and nothing is suggested.
    await switchLeadAgent(admin, false);
    const another = await newLead(agent);
    await agent
      .getByRole("region", { name: "Lead agent" })
      .getByRole("button", { name: "Ask the lead agent" })
      .click();
    await expect(
      agent.getByText(/The lead agent is switched off/),
    ).toBeVisible();
    await agent.goto(`/leads/${another.id}`);
    await expect(agent.getByText("New", { exact: true }).first()).toBeVisible();
  } finally {
    await switchLeadAgent(admin, false); // leave it as it starts
  }
});

test("a support agent sees no lead agent", async ({ browser }) => {
  const support = await signedIn(browser, USERS.support, "/leads");
  await expect(support.getByRole("region", { name: "Lead agent" })).toHaveCount(
    0,
  );
});
