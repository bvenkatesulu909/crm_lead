import { execFileSync } from "node:child_process";
import path from "node:path";

import { expect, test, type Browser, type Page } from "@playwright/test";

import { USERS, login, requireCredentials, uniqueName } from "./helpers";

/**
 * Web check (ADR 0019) end to end with the DEMO registry that lives inside the CRM: an agent
 * looks up a RERA number on a lead, the worker fetches it, the evidence appears on the lead page
 * and the agent is notified. A page that tries to carry data out arrives clean. Creates clearly
 * fictional "E2eWebcheck…" leads.
 *
 * Needs the demo sources switched on for the API and the worker: CRM_WEBCHECK_DEMO=true in the
 * environment (or backend/.env) and E2E_WEBCHECK_DEMO=1 in frontend/.env.local or the
 * environment (see docs/webcheck.md). Without it the spec is skipped.
 *
 * Also set CRM_WEBCHECK_PER_USER_HOUR=1000 for the API when you run it more than once an hour:
 * the test agent asks for several checks per run and the real limit is 10 per person per hour.
 * Like the other journeys that call the worker themselves, it expects NO standing worker.
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

/** An agent creates a lead and returns its name and address. */
async function newLead(page: Page, prefix: string) {
  const lastName = uniqueName(prefix);
  await page.goto("/leads/new");
  await page.getByLabel(/Last name/).fill(lastName);
  await page.getByRole("button", { name: "Create lead" }).click();
  await page
    .getByRole("link", { name: new RegExp(lastName) })
    .first()
    .click();
  await page.waitForURL(/\/leads\/[0-9a-f-]{36}$/);
  return { lastName, id: page.url().split("/").pop() as string };
}

const card = (page: Page) => page.getByRole("region", { name: "Web check" });

async function check(page: Page, query: string, source = "Demo RERA registry") {
  await card(page).getByLabel("Where to look").selectOption({ label: source });
  await card(page)
    .getByLabel(source.includes("company") ? "Company name" : "RERA number")
    .fill(query);
  await card(page).getByRole("button", { name: "Check" }).click();
  await expect(page.getByText(/The web check was queued/)).toBeVisible();
}

test("an agent checks a registration, sees the evidence and is told", async ({
  browser,
}) => {
  const agent = await signedIn(browser, USERS.agent1, "/leads/new");
  const lead = await newLead(agent, "E2eWebcheck");

  await expect(card(agent)).toContainText("No web check has been made yet.");
  await check(agent, "DEMO/RERA/2026/001");
  // Asking is quick; the page is fetched in the background.
  await expect(card(agent)).toContainText("No web check has been made yet.");

  runWorkerOnce();
  await agent.reload();
  const found = card(agent).getByRole("listitem").first();
  await expect(found).toContainText("Found");
  await expect(found).toContainText("Lakeview Residency");
  await expect(found).toContainText("Active");
  await expect(found).toContainText("Valid until 31 Mar 2028");
  await expect(found).toContainText("Demo RERA registry");

  await agent.goto("/notifications");
  await expect(
    agent
      .getByRole("button", {
        name: new RegExp(`Web check finished for .*${lead.lastName}.*: found`),
      })
      .first(),
  ).toBeVisible();
});

test("a page that tries to carry data out arrives clean", async ({
  browser,
}) => {
  const agent = await signedIn(browser, USERS.agent1, "/leads/new");
  await newLead(agent, "E2eWebcheck");
  await check(agent, "DEMO/RERA/2026/666");
  runWorkerOnce();
  await agent.reload();

  const item = card(agent).getByRole("listitem").first();
  await expect(item).toContainText("Villa Grande");
  await expect(item).toContainText("Some text from the page was cleaned");
  await expect(item).toContainText("[link removed]");
  // Nothing from the page reaches the screen as a picture, a link or an address.
  await expect(agent.locator('img[src*="evil.example"]')).toHaveCount(0);
  await expect(agent.locator('a[href*="evil.example"]')).toHaveCount(0);
  await expect(agent.locator("body")).not.toContainText("evil.example");
});

test("a company is looked up the same way, and an unknown number is not found", async ({
  browser,
}) => {
  const agent = await signedIn(browser, USERS.agent1, "/leads/new");
  await newLead(agent, "E2eWebcheck");
  await check(agent, "DEMO/RERA/2026/000");
  await check(agent, "Ghost Constructions", "Demo company registry");
  runWorkerOnce();
  await agent.reload();
  const items = card(agent).getByRole("listitem");
  await expect(items).toHaveCount(2);
  await expect(items.first()).toContainText("Not found");
  await expect(items.nth(1)).toContainText("Not found");
});

test("a search text in the wrong shape is refused and not repeated", async ({
  browser,
}) => {
  const agent = await signedIn(browser, USERS.agent1, "/leads/new");
  await newLead(agent, "E2eWebcheck");
  await card(agent).getByLabel("RERA number").fill("https://evil.example/x");
  await card(agent).getByRole("button", { name: "Check" }).click();
  await expect(card(agent).getByRole("alert")).toContainText(
    "The search text is not valid",
  );
  await expect(card(agent).getByRole("alert")).not.toContainText(
    "evil.example",
  );
  await expect(card(agent).getByRole("listitem")).toHaveCount(0);
});

test("who may see the card: the owner and a manager, not another agent", async ({
  browser,
}) => {
  const agent = await signedIn(browser, USERS.agent1, "/leads/new");
  const lead = await newLead(agent, "E2eWebcheck");
  await check(agent, "DEMO/RERA/2026/001");
  runWorkerOnce();

  const manager = await signedIn(browser, USERS.manager, `/leads/${lead.id}`);
  await expect(card(manager)).toContainText("Lakeview Residency");
  await expect(card(manager).getByLabel("RERA number")).toBeVisible();

  const other = await signedIn(browser, USERS.agent2, `/leads/${lead.id}`);
  await expect(other.getByText(/Page not found/i).first()).toBeVisible();
  await expect(card(other)).toHaveCount(0);
});
