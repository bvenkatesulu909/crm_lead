import { execFileSync } from "node:child_process";
import path from "node:path";

import { expect, test, type Browser, type Page } from "@playwright/test";

import { USERS, login, requireCredentials, uniqueName } from "./helpers";
import { latestMessageTo } from "./mailpit";

/**
 * Automatic follow-up drafts (ADR 0036, docs/approvals.md), end to end with a real Mailpit inbox:
 * an administrator switches the rule on; a lead whose follow-up task is due today gets ONE draft
 * (made by the worker's scan); the lead's owner reads it, rewords it and approves it; only then
 * does a real e-mail arrive, with Reply-To the owner. A lead that opted out of e-mails never gets
 * a draft, and the same lead gets no second one inside the cooldown. Creates clearly fictional
 * "E2eFollow..." leads and *.example.test addresses; the settings are put back at the end.
 *
 * Needs the worker (run once by the spec like "python -m app.worker --once") and Mailpit.
 */
test.beforeEach(() => requireCredentials());

async function signedIn(browser: Browser, user: string, target = "/") {
  const page = await (await browser.newContext()).newPage();
  await login(page, user, target);
  return page;
}

/** Runs the background worker once: it also runs the follow-up scan, then sends queued e-mail.
 * E2E_PYTHON may name another Python (a git worktree has no backend/.venv of its own). */
function runWorkerOnce() {
  execFileSync(process.env.E2E_PYTHON ?? path.join("..", "backend", ".venv", "Scripts", "python.exe"), ["-m", "app.worker", "--once"], {
    cwd: path.join("..", "backend"),
    timeout: 90_000,
    stdio: "ignore",
  });
} // prettier-ignore

/** Midday of today in UTC, written the way a datetime-local box wants it (the scan looks at the UTC day). */
function dueTodayUtc() {
  const d = new Date();
  d.setUTCHours(12, 0, 0, 0);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/** The manager writes the template the rule fills in. */
async function createTemplate(manager: Page) {
  const name = uniqueName("E2E follow-up template ");
  await manager.goto("/communications/templates/new");
  await manager.getByLabel("Name").fill(name);
  await manager.getByLabel("Subject").fill("Hello {{recipient.first_name}}");
  await manager.getByLabel("Text").fill("Dear {{recipient.full_name}},\n\nyou asked us to follow up today. Is a call this week still good for you?\n\n{{sender.name}}");
  await manager.getByRole("button", { name: "Create template" }).click();
  await expect(manager.getByText("The template was created.")).toBeVisible();
  return name;
} // prettier-ignore

/** The agent creates a lead with a fictional address, then sets the e-mail consent. */
async function createLead(agent: Page, consent: "granted" | "withdrawn") {
  const lastName = uniqueName("E2eFollow");
  const address = `${lastName.toLowerCase()}@example.test`;
  await agent.goto("/leads/new");
  await agent.getByLabel(/First name/).fill("Asha");
  await agent.getByLabel(/Last name/).fill(lastName);
  await agent.getByLabel(/^E-mail/).fill(address);
  await agent.getByRole("button", { name: "Create lead" }).click();
  await agent
    .getByRole("link", { name: new RegExp(lastName) })
    .first()
    .click();
  await agent.waitForURL(/\/leads\/[0-9a-f-]{36}$/);
  const url = new URL(agent.url()).pathname;
  await agent.goto(`${url}/edit`);
  await agent.getByLabel("E-mail consent").selectOption(consent);
  await agent.getByRole("button", { name: "Save changes" }).click();
  await expect(agent.getByText("The lead was updated.")).toBeVisible();
  return { lastName, address, url };
}

/** A follow-up task on the lead's page, due today (UTC). */
async function planTaskDueToday(agent: Page, leadUrl: string, subject: string) {
  await agent.goto(leadUrl);
  // The lead page has two "Subject" fields (e-mail dialog and task form): use the task form.
  const form = agent.locator("form").filter({
    has: agent.getByRole("button", { name: "Add to tasks" }),
  });
  await form.getByLabel("Subject").fill(subject);
  await form.getByLabel(/^Due/).fill(dueTodayUtc());
  await form.getByRole("button", { name: "Add to tasks" }).click();
  await expect(
    agent.getByText("The follow-up was added to your tasks."),
  ).toBeVisible();
}

const waiting = (page: Page) =>
  page.getByRole("region", { name: "AI proposals" });

test("a due follow-up becomes one draft; the owner rewords and approves it; an opted-out lead gets none", async ({
  browser,
}) => {
  test.setTimeout(600_000);
  const manager = await signedIn(browser, USERS.manager);
  const template = await createTemplate(manager);

  // 1. The administrator switches the rule on. A number out of range is refused and what was
  //    typed stays; a valid save is confirmed.
  const admin = await signedIn(browser, USERS.admin, "/automation/follow-ups");
  await expect(admin.getByRole("heading", { name: "Follow-ups" })).toBeVisible();
  await admin.getByLabel("Make follow-up drafts").check();
  await admin.getByLabel("E-mail template").selectOption({ label: template });
  await admin.getByLabel(/Drafts per day/).fill("500");
  await admin.getByRole("button", { name: "Save settings" }).click();
  await expect(admin.getByText(/Enter a whole number from 1 to 100/)).toBeVisible();
  await expect(admin.getByLabel(/Drafts per day/)).toHaveValue("500"); // kept
  await expect(admin.getByLabel("Make follow-up drafts")).toBeChecked();
  await admin.getByLabel(/Drafts per day/).fill("100");
  await admin.getByRole("button", { name: "Save settings" }).click();
  await expect(admin.getByText("The follow-up settings were saved.")).toBeVisible();

  // Only administrators see the page.
  const agent = await signedIn(browser, USERS.agent1);
  await agent.goto("/automation/follow-ups");
  await expect(agent.getByText("You don't have access to this page")).toBeVisible();

  // 2. Two leads of the agent, both with a task due today: one agreed to e-mails, one opted out.
  const agreed = await createLead(agent, "granted");
  await planTaskDueToday(agent, agreed.url, uniqueName("E2eCallBack"));
  const optedOut = await createLead(agent, "withdrawn");
  await planTaskDueToday(agent, optedOut.url, uniqueName("E2eCallBack"));

  // 3. The worker's scan makes ONE draft for the first lead and none for the second.
  runWorkerOnce();
  await agent.goto(agreed.url);
  const draft = waiting(agent).getByRole("link", { name: /Follow-up e-mail: Hello Asha/ });
  await expect(draft).toHaveCount(1);
  await agent.goto(optedOut.url);
  await expect(waiting(agent)).toHaveCount(0);

  // A second scan does not make another one for the same lead (a draft is waiting).
  runWorkerOnce();
  await agent.goto(agreed.url);
  await expect(waiting(agent).getByRole("link", { name: /Follow-up e-mail/ })).toHaveCount(1);

  // 4. The owner reads exactly what would be sent (plain text, the lead's own address, nothing
  //    sent yet) ...
  await waiting(agent).getByRole("link", { name: /Follow-up e-mail/ }).click();
  const mail = agent.getByRole("group", { name: "The e-mail" });
  // The first visit to this page compiles it (slow on a development server).
  await expect(mail).toContainText("Hello Asha", { timeout: 120_000 });
  await expect(mail).toContainText(`Dear Asha ${agreed.lastName},`);
  await expect(mail).not.toContainText("{{");
  await expect(agent.getByText("the follow-up assistant")).toBeVisible();
  const approvalUrl = new URL(agent.url()).pathname;
  const before = await fetch(`http://localhost:8025/api/v1/search?query=${encodeURIComponent(`to:${agreed.address}`)}`).then((r) => r.json() as Promise<{ messages: unknown[] }>);
  expect(before.messages).toHaveLength(0);

  // ... a colleague cannot open it ...
  const colleague = await signedIn(browser, USERS.agent2, approvalUrl);
  await expect(colleague.getByText("Page not found")).toBeVisible();

  // ... and the owner rewords it and approves. A link in the new text is refused and the draft
  //     keeps waiting; then the plain reword goes through.
  await agent.getByRole("button", { name: "Approve", exact: true }).click();
  const dialog = agent.getByRole("dialog");
  await expect(dialog.getByLabel("Subject")).toHaveValue("Hello Asha");
  await dialog.getByLabel("Text").fill("Hello Asha, see https://example.test/offer for the details.");
  await dialog.getByRole("button", { name: "Approve and run" }).click();
  await expect(dialog.getByText(/reworded e-mail was not accepted/)).toBeVisible();
  await dialog.getByLabel("Subject").fill("Hello Asha, a quick check-in");
  await dialog.getByLabel("Text").fill("Hello Asha,\n\nIs a call on Thursday good for you?\n\nThank you.");
  await dialog.getByRole("button", { name: "Approve and run" }).click();
  await expect(agent.getByText("The proposal was approved.")).toBeVisible();
  await expect(agent.getByRole("group", { name: "The e-mail" })).toContainText("Hello Asha, a quick check-in");

  // 5. Only now does a real e-mail go out: the reworded one, Reply-To the owner.
  runWorkerOnce();
  const sent = await latestMessageTo(agreed.address);
  expect(sent.Subject).toBe("Hello Asha, a quick check-in");
  expect(sent.Text).toContain("Is a call on Thursday good for you?");
  expect(sent.Text).not.toContain("{{");
  expect(sent.Text).not.toContain("https://");
  expect(sent.ReplyTo.map((r) => r.Address)).toEqual([expect.stringMatching(/@alpha\.example\.test$/)]);

  // 6. Another task due today on the same lead makes no second draft inside the cooldown.
  await planTaskDueToday(agent, agreed.url, uniqueName("E2eCallBackAgain"));
  runWorkerOnce();
  await agent.goto(agreed.url);
  await expect(waiting(agent)).toHaveCount(0);

  // 7. The lead opts out later: even with a new due task there is still nothing to approve.
  await agent.goto(`${agreed.url}/edit`);
  await agent.getByLabel("E-mail consent").selectOption("withdrawn");
  await agent.getByRole("button", { name: "Save changes" }).click();
  await expect(agent.getByText("The lead was updated.")).toBeVisible();
  runWorkerOnce();
  await agent.goto(agreed.url);
  await expect(waiting(agent)).toHaveCount(0);

  // Put the settings back: switched off.
  await admin.goto("/automation/follow-ups");
  await admin.getByLabel("Make follow-up drafts").uncheck();
  await admin.getByRole("button", { name: "Save settings" }).click();
  await expect(admin.getByText("The follow-up settings were saved.")).toBeVisible();
}); // prettier-ignore
