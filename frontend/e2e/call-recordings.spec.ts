import { execFileSync } from "node:child_process";
import path from "node:path";

import { expect, test, type Browser, type Page } from "@playwright/test";

import { USERS, login, requireCredentials, uniqueName } from "./helpers";

/**
 * Call recordings (ADR 0030), end to end with the SCRIPTED engine: an administrator switches the
 * feature on, a sales agent adds a recording of a call to a lead (first without the buyer's
 * agreement - refused, the form keeps its answers - then with it), the worker cleans and writes it
 * out, the card shows the transcript as text and plays the audio, the audio is deleted and the
 * transcript stays. A file that is not audio is refused, a colleague who may not read the lead
 * cannot reach it. Creates clearly fictional "E2eCalls…" leads and puts the switch back.
 *
 * Needs the scripted engine for the API and the worker (CRM_CALLS_ENGINE=fake), the file store
 * running and reachable from the browser, and E2E_CALLS_FAKE=1 here; without it the spec is
 * skipped. Like the other journeys that run the worker themselves it expects NO standing worker.
 */
test.beforeEach(() => {
  requireCredentials();
  test.skip(
    !process.env.E2E_CALLS_FAKE,
    "E2E_CALLS_FAKE is not set (the scripted call engine is switched off)",
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
  const box = admin.getByRole("article", { name: "Call recordings" });
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
  const lastName = uniqueName("E2eCalls");
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

const card = (page: Page) =>
  page.getByRole("region", { name: "Call recordings" });

/** One recording on the card, found by its file name (a refused file stays as a "failed" item). */
const item = (page: Page, fileName: string) =>
  card(page).getByTestId("call-item").filter({ hasText: fileName });

// A tiny file that starts like an mp3 (the API checks the first bytes) - fictional, silent.
const MP3 = Buffer.concat([
  Buffer.from("ID3\x04\x00\x00\x00\x00\x00\x00", "latin1"),
  Buffer.alloc(3000, 1),
]);
const NOT_AUDIO = Buffer.concat([
  Buffer.from("%PDF-1.7 a fictional document ", "latin1"),
  Buffer.alloc(500, 1),
]);

test("an agent adds a call recording, reads the transcript and deletes the audio", async ({
  browser,
}) => {
  test.setTimeout(480_000);
  const admin = await signedIn(browser, USERS.admin, "/automation/agents");
  const wasOn = await setSwitch(admin, true);
  try {
    const agent = await signedIn(browser, USERS.agent1, "/leads/new");
    await newLead(agent);
    const leadUrl = agent.url();

    await expect(card(agent)).toContainText("No call recordings yet");

    // 1. Without the buyer's agreement nothing is added, and the form keeps what was chosen.
    await card(agent)
      .getByRole("button", { name: "Add a call recording" })
      .click();
    const dialog = agent.getByRole("dialog");
    await dialog.getByLabel("Recording").setInputFiles({
      name: "site visit call.mp3",
      mimeType: "audio/mpeg",
      buffer: MP3,
    });
    await dialog.getByLabel("Language of the call").selectOption("te");
    await dialog.getByRole("button", { name: "Add", exact: true }).click();
    await expect(dialog.getByRole("alert")).toContainText(
      /buyer agreed|agreed/,
    );
    await expect(dialog.getByLabel("Language of the call")).toHaveValue("te");
    await expect(card(agent)).toContainText("No call recordings yet");

    // 2. A file that is not audio is refused after it was sent, with a sentence.
    await dialog.getByRole("checkbox", { name: /buyer agreed/ }).check();
    await dialog.getByLabel("Recording").setInputFiles({
      name: "fake call.mp3",
      mimeType: "audio/mpeg",
      buffer: NOT_AUDIO,
    });
    await dialog.getByRole("button", { name: "Add", exact: true }).click();
    await expect(dialog).toContainText(/kind of audio/);

    // 3. With the agreement and a real recording it is queued and the card says so.
    await dialog.getByLabel("Recording").setInputFiles({
      name: "site visit call.mp3",
      mimeType: "audio/mpeg",
      buffer: MP3,
    });
    await dialog.getByRole("button", { name: "Add", exact: true }).click();
    await expect(agent.getByText(/The recording was added/)).toBeVisible();
    await expect(agent.getByRole("dialog")).toHaveCount(0); // closed itself, nothing blocks the page
    const good = item(agent, "site visit call.mp3");
    await expect(good.getByTestId("call-status")).toContainText(
      /cleaned and transcribed/,
    );
    await expect(good).toContainText("Telugu");
    // The refused file stays visible as a failed item, with the reason in words.
    const refused = item(agent, "fake call.mp3");
    await expect(refused.getByTestId("call-status")).toHaveText(
      "Could not be processed",
    );
    await expect(refused).toContainText(/not the kind of audio/);
    await expect(refused.getByRole("button", { name: "Listen" })).toHaveCount(
      0,
    );

    // 4. The worker cleans and writes it out; the card shows the transcript as text.
    runWorkerOnce();
    await agent.reload();
    await expect(good.getByTestId("call-status")).toHaveText(
      "Transcript ready",
    );
    await good.getByRole("button", { name: "Show transcript" }).click();
    const transcript = good.getByTestId("call-transcript");
    await expect(transcript).toContainText("Automatic transcript");
    await expect(transcript).toContainText("నమస్కారం");
    await expect(transcript).toContainText("0:00");

    // 5. Listening: the player gets a short link to the file store.
    await good.getByRole("button", { name: "Listen" }).click();
    const player = good.locator("audio");
    await expect(player).toHaveAttribute("src", /^https?:\/\//);

    // 6. Deleting the audio keeps the transcript and the card says when.
    await good.getByRole("button", { name: "Delete audio" }).click();
    await agent
      .getByRole("dialog")
      .getByRole("button", { name: "Delete audio" })
      .click();
    await expect(agent.getByText(/The audio was deleted\./)).toBeVisible();
    await expect(agent.getByRole("dialog")).toHaveCount(0);
    await expect(good).toContainText("The audio was deleted on");
    await expect(good.getByRole("button", { name: "Listen" })).toHaveCount(0);
    // The transcript that was open stays open and stays readable.
    await expect(good.getByTestId("call-transcript")).toContainText("నమస్కారం");

    // 7. A colleague who may not read this lead cannot reach it at all.
    const other = await signedIn(browser, USERS.agent2, "/");
    await other.goto(leadUrl);
    await expect(
      other.getByText(/Page not found|not found/i).first(),
    ).toBeVisible();
    await expect(other.getByText("నమస్కారం")).toHaveCount(0);
  } finally {
    if (!wasOn) await setSwitch(admin, false);
  }
});

test("with the feature off, adding a recording says so in words", async ({
  browser,
}) => {
  test.setTimeout(120_000);
  const admin = await signedIn(browser, USERS.admin, "/automation/agents");
  const wasOn = await setSwitch(admin, false);
  try {
    const agent = await signedIn(browser, USERS.agent1, "/leads/new");
    await newLead(agent);
    await card(agent)
      .getByRole("button", { name: "Add a call recording" })
      .click();
    const dialog = agent.getByRole("dialog");
    await dialog.getByLabel("Recording").setInputFiles({
      name: "call.mp3",
      mimeType: "audio/mpeg",
      buffer: MP3,
    });
    await dialog.getByRole("checkbox", { name: /buyer agreed/ }).check();
    await dialog.getByRole("button", { name: "Add", exact: true }).click();
    await expect(dialog).toContainText(/switched off/);
  } finally {
    if (wasOn) await setSwitch(admin, true);
  }
});
