import { execFileSync } from "node:child_process";
import path from "node:path";

import { expect, test, type Browser, type Page } from "@playwright/test";

import { USERS, login, requireCredentials, uniqueName } from "./helpers";

/**
 * Company details on a lead (BP-02, ADR 0026) end to end with the DEMO company sites that live
 * inside the CRM: an agent asks for the details of a lead whose website is a demo site, the
 * worker reads it, the card shows suggestions next to the current values, the agent saves them and
 * the lead page changes - and only then. A lead with a free-mail address is refused with a
 * sentence, not an error page. Creates clearly fictional "E2eCompanyDetails…" leads and switches
 * the feature on for the organisation, then back to how it was found.
 *
 * Needs the demo sources switched on for the API and the worker (CRM_WEBCHECK_DEMO=true) and
 * E2E_WEBCHECK_DEMO=1 here; without it the spec is skipped. Like the other journeys that run the
 * worker themselves it expects NO standing worker, and a CRM_COMPANY_DETAILS_PER_USER_HOUR high
 * enough for repeated runs.
 */
test.beforeEach(() => {
  requireCredentials();
  test.skip(
    !process.env.E2E_WEBCHECK_DEMO,
    "E2E_WEBCHECK_DEMO is not set (the demo web check sources are switched off)",
  );
});

function runWorkerOnce() {
  execFileSync(
    path.join("..", "backend", ".venv", "Scripts", "python.exe"),
    ["-m", "app.worker", "--once"],
    { cwd: path.join("..", "backend"), timeout: 90_000, stdio: "ignore" },
  );
}

async function signedIn(
  browser: Browser,
  user: string,
  target = "/",
): Promise<Page> {
  const page = await (await browser.newContext()).newPage();
  await login(page, user, target);
  return page;
}

/** Switch the registry entry on or off as the administrator; returns whether it was on. */
async function setSwitch(admin: Page, on: boolean): Promise<boolean> {
  await admin.goto("/automation/agents");
  const box = admin.getByRole("article", { name: "Company details" });
  await expect(box).toBeVisible();
  const toggle = box.getByLabel("Switched on");
  const wasOn = await toggle.isChecked();
  if (wasOn !== on) {
    await toggle.setChecked(on);
    await box.getByRole("button", { name: "Save settings" }).click();
    await expect(admin.getByText(/were saved/)).toBeVisible();
  }
  return wasOn;
}

/** An agent creates a lead with the given company fields and opens it. */
async function newLead(
  page: Page,
  fields: { website?: string; email?: string },
) {
  const lastName = uniqueName("E2eCompanyDetails");
  await page.goto("/leads/new");
  await page.getByLabel(/Last name/).fill(lastName);
  if (fields.email) await page.getByLabel(/E-mail/).fill(fields.email);
  if (fields.website)
    await page
      .getByRole("group", { name: "About the company" })
      .getByLabel(/Website/)
      .fill(fields.website);
  await page.getByRole("button", { name: "Create lead" }).click();
  await page
    .getByRole("link", { name: new RegExp(lastName) })
    .first()
    .click();
  await page.waitForURL(/\/leads\/[0-9a-f-]{36}$/);
  return { lastName, id: page.url().split("/").pop() as string };
}

const card = (page: Page) =>
  page.getByRole("region", { name: "Company details" });

test("an agent looks up a company, sees the suggestions and saves them", async ({
  browser,
}) => {
  test.setTimeout(180_000);
  const admin = await signedIn(browser, USERS.admin, "/automation/agents");
  const wasOn = await setSwitch(admin, true);
  try {
    const agent = await signedIn(browser, USERS.agent1, "/leads/new");
    await newLead(agent, { website: "acme-builders.demo.example" });

    await expect(card(agent)).toContainText("No look-up yet");
    await card(agent)
      .getByRole("button", { name: "Find company details" })
      .click();
    await expect(agent.getByText(/The look-up was queued/)).toBeVisible();

    runWorkerOnce();
    await agent.reload();
    await expect(card(agent)).toContainText("Found on the company's website");
    const row = (name: string) =>
      card(agent).getByRole("row").filter({ hasText: name });
    await expect(row("Industry")).toContainText("Real estate");
    await expect(row("Employees")).toContainText("11-50");
    // Nothing is on the lead yet: the details list still shows dashes.
    const term = (name: string) =>
      agent
        .getByRole("term")
        .filter({ hasText: new RegExp(`^${name}$`) })
        .locator("+ dd");
    await expect(term("Industry")).toHaveText("—");

    // Untick the size, save the rest.
    await card(agent).getByLabel("Save Employees").uncheck();
    await card(agent)
      .getByRole("button", { name: "Save the ticked details" })
      .click();
    await expect(
      agent.getByText("The chosen company details were saved on the lead."),
    ).toBeVisible();
    await expect(term("Industry")).toHaveText("Real estate");
    await expect(term("Employees")).toHaveText("—");
    // The page that was read is shown as text, never as a link to it.
    await expect(
      agent.locator('a[href*="acme-builders.demo.example"]'),
    ).toHaveCount(0);

    // A colleague who may not read this lead cannot reach it at all.
    const other = await signedIn(browser, USERS.agent2, "/");
    const lead = agent.url();
    await other.goto(lead);
    await expect(
      other.getByText(/Page not found|not found/i).first(),
    ).toBeVisible();
    await expect(card(other)).toHaveCount(0);
  } finally {
    await setSwitch(admin, wasOn);
  }
});

test("a lead with only a free-mail address is told what to add", async ({
  browser,
}) => {
  test.setTimeout(120_000);
  const admin = await signedIn(browser, USERS.admin, "/automation/agents");
  const wasOn = await setSwitch(admin, true);
  try {
    const agent = await signedIn(browser, USERS.agent1, "/leads/new");
    await newLead(agent, { email: "someone@gmail.com" });
    await card(agent)
      .getByRole("button", { name: "Find company details" })
      .click();
    await expect(card(agent)).toContainText("free mail service");
    await expect(card(agent)).toContainText("No look-up yet");
  } finally {
    await setSwitch(admin, wasOn);
  }
});
