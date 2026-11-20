import { execFileSync } from "node:child_process";
import path from "node:path";

import { expect, test, type Browser, type Page } from "@playwright/test";

import { USERS, login, requireCredentials, uniqueName } from "./helpers";

/**
 * Call notes and the deal checklist (ADR 0035), end to end with the SCRIPTED engines: an
 * administrator chooses the frame and switches the feature on, a sales agent adds a recording, the
 * worker writes the transcript, the agent asks for call notes (first while the feature is off - a
 * sentence says so - then on), every line shows its state, the quote and the moment, the first
 * line is stated (the scripted model quotes the first words of the call) and the rest unknown, the
 * agent suggests it to the buyer memory, a manager approves it and ONLY THEN does the buyer memory
 * show it - as an assumption, never a fact. A colleague cannot reach the lead. Creates clearly
 * fictional "E2eNotes..." leads and puts the switches and the frame back.
 *
 * Needs the scripted call engine and the scripted AI provider for the API and the worker
 * (CRM_CALLS_ENGINE=fake, CRM_AI_PROVIDER=fake), the file store, and E2E_CALLS_FAKE=1 plus
 * E2E_FAKE_ASSISTANT=1 here; without them the spec is skipped. It runs the worker itself, so it
 * expects NO standing worker.
 */
test.beforeEach(() => {
  requireCredentials();
  test.skip(
    !process.env.E2E_CALLS_FAKE || !process.env.E2E_FAKE_ASSISTANT,
    "the scripted call engine or the scripted AI provider is switched off",
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

/** Switch one registry entry on or off as the administrator; returns whether it was on. */
async function setSwitch(
  admin: Page,
  title: string,
  on: boolean,
): Promise<boolean> {
  await admin.goto("/automation/agents");
  const box = admin.getByRole("article", { name: title });
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

async function newLead(page: Page): Promise<string> {
  const lastName = uniqueName("E2eNotes");
  await page.goto("/leads/new");
  await page.getByLabel(/Last name/).fill(lastName);
  await page.getByRole("button", { name: "Create lead" }).click();
  await page
    .getByRole("link", { name: new RegExp(lastName) })
    .first()
    .click();
  await page.waitForURL(/\/leads\/[0-9a-f-]{36}$/);
  return lastName;
}

const callsCard = (page: Page) =>
  page.getByRole("region", { name: "Call recordings" });
const notes = (page: Page) => page.getByTestId("call-notes");
const memory = (page: Page) =>
  page.getByRole("region", { name: "Buyer memory" });

const MP3 = Buffer.concat([
  Buffer.from("ID3\x04\x00\x00\x00\x00\x00\x00", "latin1"),
  Buffer.alloc(40_000, 1),
]);

test("an agent asks for call notes, suggests them, and only an approval changes the buyer memory", async ({
  browser,
}) => {
  test.setTimeout(600_000);
  const admin = await signedIn(browser, USERS.admin, "/automation/agents");
  const calls = await setSwitch(admin, "Call recordings", true);
  const callNotes = await setSwitch(admin, "Call notes", false);
  try {
    // 1. The administrator chooses the frame; the choice is kept.
    await admin.goto("/automation/call-notes");
    await admin.getByLabel(/MEDDIC/).check();
    await admin.getByRole("button", { name: "Save" }).click();
    await expect(
      admin.getByText("The checklist frame was saved."),
    ).toBeVisible();
    await expect(admin.getByLabel(/MEDDIC/)).toBeChecked();
    await admin.getByLabel(/BANT/).check();
    await admin.getByRole("button", { name: "Save" }).click();
    await expect(
      admin.getByText("The checklist frame was saved."),
    ).toBeVisible();
    await expect(admin.getByLabel(/BANT/)).toBeChecked();

    // 2. An agent adds a recording; the worker writes the transcript.
    const agent = await signedIn(browser, USERS.agent1, "/leads/new");
    await newLead(agent);
    const leadUrl = agent.url();
    await callsCard(agent)
      .getByRole("button", { name: "Add a call recording" })
      .click();
    const dialog = agent.getByRole("dialog");
    await dialog.getByLabel("Recording").setInputFiles({
      name: "notes call.mp3",
      mimeType: "audio/mpeg",
      buffer: MP3,
    });
    await dialog.getByLabel("Language of the call").selectOption("en");
    await dialog.getByRole("checkbox", { name: /buyer agreed/ }).check();
    await dialog.getByRole("button", { name: "Add", exact: true }).click();
    await expect(agent.getByText(/The recording was added/)).toBeVisible();
    runWorkerOnce();
    await agent.reload();
    const item = callsCard(agent).getByTestId("call-item");
    await expect(item.getByTestId("call-status")).toHaveText(
      "Transcript ready",
    );
    await item.getByRole("button", { name: "Show transcript" }).click();
    await expect(notes(agent)).toContainText("An AI draft");
    await expect(notes(agent)).toContainText("No call notes yet");

    // 3. While the feature is off a sentence says so and nothing is made.
    await notes(agent)
      .getByRole("button", { name: "Create call notes" })
      .click();
    await expect(notes(agent).getByRole("alert")).toContainText(/switched off/);
    await expect(notes(agent).getByTestId("notes-draft")).toHaveCount(0);

    // 4. Switched on, the agent gets a draft: first line stated with quote and moment, rest unknown.
    await setSwitch(admin, "Call notes", true);
    await notes(agent)
      .getByRole("button", { name: "Create call notes" })
      .click();
    const draft = notes(agent).getByTestId("notes-draft");
    await expect(draft).toContainText("BANT checklist · version 1");
    const lines = draft.getByTestId("notes-line");
    await expect(lines).toHaveCount(4);
    await expect(lines.nth(0).getByTestId("notes-state")).toHaveText("Stated");
    await expect(lines.nth(0).getByTestId("notes-quote")).toContainText(
      "Hello, I am looking for a three bedroom flat in Kokapet.",
    );
    await expect(lines.nth(0)).toContainText("Speaker not verified");
    await expect(lines.nth(1).getByTestId("notes-state")).toHaveText("Unknown");
    await expect(lines.nth(1)).toContainText(
      "Nothing on this call answers it.",
    );

    // 5. Listening starts at the moment of the quote.
    await lines.nth(0).getByRole("button", { name: "Listen at 0:00" }).click();
    await expect(notes(agent).locator("audio")).toHaveAttribute(
      "src",
      /^https?:\/\/.*#t=0$/,
    );

    // 6. Suggesting to the buyer memory: a preview, nothing changes yet.
    await notes(agent)
      .getByRole("button", { name: "Suggest to buyer memory…" })
      .click();
    const suggest = notes(agent).getByTestId("notes-suggest");
    await expect(suggest).toContainText("assumptions, not facts");
    await expect(suggest).toContainText("Budget:");
    await expect(suggest).toContainText("Follow-up task:");
    await suggest.getByRole("button", { name: "Send for approval" }).click();
    const outcomes = notes(agent).getByTestId("notes-outcomes");
    await expect(outcomes).toContainText("Nothing has changed yet");
    await expect(outcomes).toContainText("Waiting for a different person");
    await expect(memory(agent)).not.toContainText("Hello, I am");

    // 7. The asker cannot approve; a colleague cannot reach the lead.
    await agent.goto("/approvals");
    await expect(
      agent.getByRole("button", { name: "Approve", exact: true }),
    ).toHaveCount(0);
    const other = await signedIn(browser, USERS.agent2, "/");
    await other.goto(leadUrl);
    await expect(other.getByText(/not found/i).first()).toBeVisible();

    // 8. A manager approves the buyer memory suggestion; only now does the memory show it.
    const manager = await signedIn(browser, USERS.manager, "/approvals");
    const waiting = manager
      .getByRole("article")
      .filter({ hasText: "the call notes agent" })
      .filter({ hasText: "buyer memory" });
    await expect(waiting).toContainText("as an assumption (not a fact)");
    await waiting.getByRole("button", { name: "Approve", exact: true }).click();
    await waiting.getByRole("button", { name: "Approve and run" }).click();
    await expect(manager.getByText("The proposal was approved.")).toBeVisible();
    await agent.goto(leadUrl);
    const guesses = memory(agent).getByRole("region", { name: "Assumptions" });
    await expect(guesses).toContainText("Hello, I am");
    // It is an assumption, never a fact: there is no Facts group at all.
    await expect(memory(agent)).toContainText("0 facts · 1 assumption");
    await expect(
      memory(agent).getByRole("region", { name: "Facts" }),
    ).toHaveCount(0);
  } finally {
    await setSwitch(admin, "Call notes", callNotes);
    if (!calls) await setSwitch(admin, "Call recordings", false);
  }
});

test("only administrators see the call notes settings", async ({ browser }) => {
  const agent = await signedIn(browser, USERS.agent1, "/");
  await expect(
    agent.getByRole("link", { name: "Call notes", exact: true }),
  ).toHaveCount(0);
  await agent.goto("/automation/call-notes");
  await expect(
    agent.getByText(/don't have access to this page/i).first(),
  ).toBeVisible();
  const admin = await signedIn(browser, USERS.admin, "/");
  await expect(
    admin.getByRole("link", { name: "Call notes", exact: true }),
  ).toBeVisible();
});
