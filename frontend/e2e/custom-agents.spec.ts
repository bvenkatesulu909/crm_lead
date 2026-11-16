import { expect, test, type Browser, type Page } from "@playwright/test";

import { USERS, login, requireCredentials, uniqueName } from "./helpers";

/**
 * The no-code agent builder (ADR 0034, docs/custom-agents.md), end to end with the SCRIPTED model:
 * an administrator defines an agent from the fixed menus, tries it on a real lead (a dry run that
 * shows what it would suggest and changes nothing), switches it on, a sales agent presses its Run
 * button on the lead, the agent only SUGGESTS (a proposal waits and names the custom agent), a
 * manager approves, and the administrator retires the agent. Creates clearly fictional
 * "E2eCustomAgent..." records and retires its agent at the end.
 *
 * Needs the scripted model: CRM_AI_PROVIDER=fake for the API and E2E_FAKE_ASSISTANT=1 for this run
 * (the same switch as the approvals and lead agent journeys). The scripted agent suggests a
 * follow-up task. Without the switch the spec is skipped.
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

/** A sales agent creates a new lead; it is theirs, so they may run agents on it. */
async function newLead(page: Page) {
  const lastName = uniqueName("E2eCustomAgent");
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

test("an admin defines, tries and switches on an agent; sales runs it; a manager decides", async ({
  browser,
}) => {
  test.setTimeout(300_000);
  const name = uniqueName("E2eCustomAgent");
  const admin = await signedIn(
    browser,
    USERS.admin,
    "/automation/custom-agents",
  );
  let created = false;
  try {
    // 1. Define it from the fixed menus. It starts switched off.
    await admin.getByRole("link", { name: "New custom agent" }).first().click();
    await admin.getByLabel("Name", { exact: true }).fill(name);
    await admin
      .getByLabel("What it is for")
      .fill("Suggest a follow-up task for a lead.");
    await admin
      .getByLabel("Instruction")
      .fill("Read the lead.\nSuggest one follow-up task.");
    await admin.getByLabel(/The lead's own fields/).check();
    await expect(admin.getByText("This agent works on a lead.")).toBeVisible();
    await admin.getByLabel(/Suggest a follow-up task for the owner/).check();
    await admin.getByRole("button", { name: "Create the agent" }).click();
    created = true;
    await expect(admin.getByText(/The agent was created/)).toBeVisible();
    await expect(
      admin.getByText("Needs a dry run, then switching on").first(),
    ).toBeVisible();
    await expect(
      admin.getByRole("button", { name: "Switch on" }),
    ).toBeDisabled();

    // 2. A refused save keeps what the administrator chose.
    await admin.getByLabel("Name", { exact: true }).fill("");
    await admin.getByRole("button", { name: "Save as a new version" }).click();
    await expect(
      admin.getByRole("alert").filter({ hasText: "could not be saved" }),
    ).toBeVisible();
    await expect(admin.getByLabel(/The lead's own fields/)).toBeChecked();
    await expect(
      admin.getByLabel(/Suggest a follow-up task for the owner/),
    ).toBeChecked();
    await admin.getByLabel("Name", { exact: true }).fill(name);

    // 3. A sales agent creates a lead.
    const agent = await signedIn(browser, USERS.agent1, "/leads/new");
    const lead = await newLead(agent);
    // No agent is switched on yet, so the lead page offers no Run button.
    await expect(
      agent.getByRole("region", { name: "Custom agents" }),
    ).toHaveCount(0);

    // 4. The dry run shows what it WOULD do; nothing is proposed.
    await admin.reload();
    const trial = admin.getByRole("form", { name: "Try the agent" });
    await trial.getByLabel("Lead").selectOption({ label: lead.lastName });
    await trial.getByRole("button", { name: /Try it/ }).click();
    await expect(trial).toContainText("would: Create a follow-up task");
    await expect(trial).toContainText("Nothing was proposed");

    // 5. Now it can be switched on.
    await admin.reload();
    await admin.getByRole("button", { name: "Switch on" }).click();
    await expect(admin.getByText(/The agent is switched on/)).toBeVisible();

    // 6. The sales agent presses Run: a suggestion waits, the lead has no new task yet.
    await agent.goto(`/leads/${lead.id}`);
    const card = agent.getByRole("region", { name: "Custom agents" });
    await card.getByRole("button", { name: `Run ${name}` }).click();
    await expect(card.getByRole("status")).toContainText(
      "Nothing changes until a different person approves it",
    );
    await expect(
      card.getByRole("link", { name: "Open the suggestion" }),
    ).toBeVisible();

    // 7. A second run on the same lead within the hour is refused in plain words.
    await card.getByRole("button", { name: `Run ${name}` }).click();
    await expect(card.getByRole("alert")).toContainText(/a moment ago/);

    // 8. A manager sees the proposal named after the custom agent, and approves it.
    const manager = await signedIn(browser, USERS.manager, "/approvals");
    const waiting = manager
      .getByRole("article")
      .filter({ hasText: lead.lastName });
    await expect(waiting).toContainText(`the custom agent "${name}"`);
    await waiting.getByRole("button", { name: "Approve", exact: true }).click();
    await waiting.getByRole("button", { name: "Approve and run" }).click();
    // The first visit of a page compiles it in the dev server, which can take several seconds.
    await expect(manager.getByText("The proposal was approved.")).toBeVisible({
      timeout: 45_000,
    });

    // 9. The administrator sees both the dry run and the run in the agent's history.
    await admin.reload();
    await expect(admin.getByText(/Dry run of version 1/)).toBeVisible();
    await expect(admin.getByText(/Run of version 1/).first()).toBeVisible();

    // 10. Support staff see nothing of custom agents.
    const support = await signedIn(browser, USERS.support, "/leads");
    await expect(
      support.getByRole("region", { name: "Custom agents" }),
    ).toHaveCount(0);
    await support.goto("/automation/custom-agents");
    await expect(
      support.getByRole("heading", { name: "Custom agents", level: 1 }),
    ).toHaveCount(0);
  } finally {
    // Leave the organisation as it was: retire the agent.
    if (created) {
      await admin.goto("/automation/custom-agents");
      const row = admin.getByRole("link", { name });
      if (await row.count()) {
        await row.first().click();
        admin.once("dialog", (dialog) => void dialog.accept());
        await admin.getByRole("button", { name: "Retire this agent" }).click();
        await expect(admin.getByText("The agent was retired.")).toBeVisible();
      }
    }
  }
});

test("a sales agent has no builder page and no menu entry", async ({
  browser,
}) => {
  const agent = await signedIn(browser, USERS.agent1, "/leads");
  await expect(agent.getByRole("link", { name: "Custom agents" })).toHaveCount(
    0,
  );
  await agent.goto("/automation/custom-agents");
  await expect(
    agent.getByRole("heading", { name: "Custom agents", level: 1 }),
  ).toHaveCount(0);
});
