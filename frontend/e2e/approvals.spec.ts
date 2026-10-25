import { execFileSync } from "node:child_process";
import path from "node:path";

import { expect, test, type Browser, type Page } from "@playwright/test";

import { USERS, login, requireCredentials, uniqueName } from "./helpers";

/**
 * Approval queue for AI-proposed actions (ADR 0014, BP-05), end to end with the SCRIPTED
 * assistant: an agent asks the assistant to change a lead, the assistant only PROPOSES, a
 * different person approves (or rejects) it, and only then does the lead change. Creates clearly
 * fictional "E2eApprove…" leads.
 *
 * Needs the scripted assistant: CRM_AI_PROVIDER=fake in backend/.env and E2E_FAKE_ASSISTANT=1 in
 * frontend/.env.local (see docs/approvals.md). Without it the spec is skipped.
 */
test.beforeEach(() => {
  requireCredentials();
  test.skip(
    !process.env.E2E_FAKE_ASSISTANT,
    "E2E_FAKE_ASSISTANT is not set in .env.local (scripted assistant switched off)",
  );
});

function runWorkerOnce() {
  execFileSync(path.join("..", "backend", ".venv", "Scripts", "python.exe"), ["-m", "app.worker", "--once"], {
    cwd: path.join("..", "backend"), timeout: 60_000, stdio: "ignore",
  });
} // prettier-ignore

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

/** The agent asks the assistant to propose a status change; returns the proposal's address. */
async function askForStatus(
  page: Page,
  leadId: string,
  status: string,
  because: string,
) {
  await page.goto("/assistant");
  await page
    .getByLabel("Question")
    .fill(`Please mark lead ${leadId} as ${status} because ${because}`);
  await page.getByRole("button", { name: "Ask assistant" }).click();
  const waiting = page.getByRole("region", { name: "Waiting for approval" });
  await expect(waiting).toBeVisible();
  await expect(waiting).toContainText("Nothing has changed yet");
  const link = waiting.getByRole("link", {
    name: `Change the lead's status to ${status}`,
  });
  const href = await link.getAttribute("href");
  expect(href).toMatch(/^\/approvals\/[0-9a-f-]{36}$/);
  return href as string;
}

test("the assistant proposes, a manager approves, and only then the lead changes", async ({
  browser,
}) => {
  test.setTimeout(180_000);
  const agent = await signedIn(browser, USERS.agent1, "/leads/new");
  const lead = await newLead(agent, "E2eApprove");

  // 1. The assistant proposes; the lead is still "New".
  const proposal = await askForStatus(agent, lead.id, "contacted", "the buyer answered my call.");
  await agent.goto(`/leads/${lead.id}`);
  await expect(agent.getByRole("region", { name: "AI proposals" })).toContainText(
    "Change the lead's status to contacted",
  );
  await expect(agent.getByText("New", { exact: true }).first()).toBeVisible();

  // 2. The asker can't decide on their own proposal; a colleague can't even see it.
  await agent.goto(proposal);
  await expect(agent.getByText("You asked for this, so someone else has to decide on it.")).toBeVisible();
  await expect(agent.getByRole("button", { name: "Approve", exact: true })).toHaveCount(0);
  const colleague = await signedIn(browser, USERS.agent2, proposal);
  await expect(colleague.getByText(/not found|doesn't exist/i).first()).toBeVisible();

  // 3. A manager sees it in the queue and approves it.
  const manager = await signedIn(browser, USERS.manager, "/approvals");
  const card = manager.getByRole("article").filter({ hasText: lead.lastName });
  await expect(card).toContainText("the buyer answered my call.");
  await expect(card).toContainText("Waiting");
  await card.getByRole("button", { name: "Approve", exact: true }).click();
  await card.getByRole("button", { name: "Approve and run" }).click();
  await expect(manager.getByText("The proposal was approved.")).toBeVisible();
  await expect(manager.getByText("Approved", { exact: true })).toBeVisible();
  await expect(manager.getByText("Result: Lead status changed to contacted.")).toBeVisible();

  // 4. Now - and only now - the lead has changed.
  await manager.goto(`/leads/${lead.id}`);
  await expect(manager.getByText("Contacted", { exact: true }).first()).toBeVisible();
  await expect(manager.getByRole("region", { name: "AI proposals" })).toHaveCount(0);

  // 5. A second decision is refused, and the right people were told.
  await manager.goto(proposal);
  await expect(manager.getByRole("button", { name: "Approve", exact: true })).toHaveCount(0);
  runWorkerOnce();
  await agent.goto("/notifications");
  await expect(
    agent.getByRole("button", { name: /Your AI proposal was approved: Change the lead's status to contacted/ }).first(),
  ).toBeVisible();
  await manager.goto("/notifications");
  await expect(
    manager.getByRole("button", { name: /AI proposal waiting for approval: Change the lead's status to contacted/ }).first(),
  ).toBeVisible();
}); // prettier-ignore

test("a rejection needs a reason and changes nothing", async ({ browser }) => {
  test.setTimeout(150_000);
  const agent = await signedIn(browser, USERS.agent1, "/leads/new");
  const lead = await newLead(agent, "E2eReject");
  await askForStatus(agent, lead.id, "qualified", "the budget is confirmed.");

  const manager = await signedIn(browser, USERS.manager, "/approvals");
  const card = manager.getByRole("article").filter({ hasText: lead.lastName });
  await card.getByRole("button", { name: "Reject", exact: true }).click();
  await card.getByRole("button", { name: "Reject proposal" }).click();
  await expect(card.getByText("Say why you reject it, so the colleague knows.")).toBeVisible();
  await card.getByLabel("Why?").fill("Call the buyer first.");
  await card.getByRole("button", { name: "Reject proposal" }).click();
  await expect(manager.getByText("The proposal was rejected.")).toBeVisible();
  await expect(manager.getByText("Rejected", { exact: true })).toBeVisible();

  // The agent sees why, and the lead is unchanged.
  await agent.goto("/approvals?tab=mine");
  const mine = agent.getByRole("article").filter({ hasText: lead.lastName });
  await expect(mine).toContainText("Rejected");
  await expect(mine).toContainText("Note: Call the buyer first.");
  await agent.goto(`/leads/${lead.id}`);
  await expect(agent.getByText("New", { exact: true }).first()).toBeVisible();
}); // prettier-ignore
