import { expect, test, type Page } from "@playwright/test";

import { USERS, login, requireCredentials, uniqueName } from "./helpers";

/**
 * Drafting a buyer-video script with the drafter and sending it for approval (ADR 0041, VB4-VB5),
 * end to end. Needs `CRM_AI_PROVIDER=fake` on the API (a scripted drafter, no key). An administrator
 * switches the drafter on; an agent confirms a fact in buyer memory, opens the video brief and presses
 * "Draft with AI" - the box fills and says the draft is neither saved nor approved; "Send for
 * approval" queues it; the asker cannot approve it, a manager does, and only then does the script
 * show up under saved scripts as an approved AI draft. Switched off again, the drafter explains
 * why. Creates a clearly fictional "E2eDraft…" lead.
 */
test.beforeEach(() => {
  requireCredentials();
  test.skip(
    !process.env.E2E_FAKE_ASSISTANT,
    "E2E_FAKE_ASSISTANT is not set (scripted model switched off)",
  );
});

async function setDrafter(page: Page, on: boolean) {
  await page.goto("/automation/agents");
  const box = page.getByRole("article", { name: "Video script drafter" });
  const toggle = box.getByLabel("Switched on");
  if ((await toggle.isChecked()) !== on) {
    if (on) await toggle.check();
    else await toggle.uncheck();
    await box.getByRole("button", { name: "Save settings" }).click();
    await expect(page.getByText(/were saved/)).toBeVisible();
  }
}

test("an agent drafts a script, sends it, and only a manager's approval saves it", async ({
  browser,
}) => {
  test.setTimeout(240_000);
  const admin = await (await browser.newContext()).newPage();
  await login(admin, USERS.admin, "/automation/agents");
  await setDrafter(admin, true);

  const lastName = uniqueName("E2eDraft");
  const agent = await (await browser.newContext()).newPage();
  await login(agent, USERS.agent1, "/leads/new");
  await agent.getByLabel(/First name/).fill("Suresh");
  await agent.getByLabel(/Last name/).fill(lastName);
  await agent.getByLabel(/Property type/).selectOption({ label: "Apartment" });
  await agent.getByLabel(/Minimum budget/).fill("1.2 Cr");
  await agent.getByLabel(/Maximum budget/).fill("1.5 Cr");
  await agent.getByLabel(/Location/).fill("Kokapet, Hyderabad");
  await agent.getByRole("button", { name: "Create lead" }).click();
  await agent
    .getByRole("link", { name: new RegExp(lastName) })
    .first()
    .click();
  await agent.waitForURL(/\/leads\/[0-9a-f-]{36}$/);
  const leadUrl = agent.url();
  const leadId = leadUrl.split("/").pop() as string;

  // A confirmed fact for the drafter to use: copy the lead form into buyer memory.
  const memory = agent.getByRole("region", { name: "Buyer memory" });
  await memory.getByRole("button", { name: "Copy from the lead form" }).click();
  await expect(memory).toContainText("3 facts");

  // 1. Draft with AI: the box fills, and the draft is marked as neither saved nor approved.
  const url = `/print/leads/${leadId}/video-brief`;
  await agent.goto(url);
  await agent.getByRole("button", { name: "Draft with AI" }).click();
  await expect(agent.getByText(/not saved and not approved/i)).toBeVisible();
  const box = agent.getByLabel(/Your script/);
  await expect(box).toHaveValue(/Hello Suresh,/);
  await expect(agent.getByText("No script saved yet.")).toBeVisible();

  // 2. Send it for approval: a notice with a link, and still nothing saved.
  await agent.getByRole("button", { name: "Send for approval" }).click();
  await expect(agent.getByRole("status")).toContainText(
    /waits for a colleague/i,
  );
  const link = agent.getByRole("link", { name: "Open the approval" });
  const approvalPath = (await link.getAttribute("href")) as string;
  expect(approvalPath).toMatch(/^\/approvals\/[0-9a-f-]{36}$/);
  await expect(agent.getByText("No script saved yet.")).toBeVisible();

  // 3. The asker cannot approve it; a manager can, and then the script is saved as an AI draft.
  await agent.goto(approvalPath);
  await expect(
    agent.getByText("the video script drafter").first(),
  ).toBeVisible();
  await expect(
    agent.getByRole("button", { name: "Approve", exact: true }),
  ).toHaveCount(0);
  const manager = await (await browser.newContext()).newPage();
  await login(manager, USERS.manager, "/approvals");
  const waiting = manager
    .getByRole("article")
    .filter({ hasText: "video script drafter" });
  await expect(waiting).toContainText("Video script");
  await waiting.getByRole("button", { name: "Approve", exact: true }).click();
  await waiting.getByRole("button", { name: "Approve and run" }).click();
  await expect(manager.getByText("The proposal was approved.")).toBeVisible();

  await agent.goto(url);
  const saved = agent.getByRole("region", { name: "Saved scripts" });
  await expect(saved).toContainText("Version 1");
  await expect(saved).toContainText("AI draft, approved by a colleague");

  // 4. A script with a made-up number is refused before it reaches the queue.
  await agent
    .getByLabel(/Your script/)
    .fill("Hello Suresh,\nOnly ₹90,00,000 today.");
  await agent.getByRole("button", { name: "Send for approval" }).click();
  await expect(
    agent.getByText(/number, amount or date|not in the buyer's facts/i).first(),
  ).toBeVisible();

  // 5. Switched off again, the drafter explains why instead of drafting.
  await setDrafter(admin, false);
  await agent.goto(url);
  await agent.getByRole("button", { name: "Draft with AI" }).click();
  await expect(agent.getByText(/switched off/i).first()).toBeVisible();
});
