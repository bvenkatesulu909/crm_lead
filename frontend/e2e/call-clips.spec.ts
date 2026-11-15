import { execFileSync } from "node:child_process";
import path from "node:path";

import { expect, test, type Browser, type Page } from "@playwright/test";

import { USERS, login, requireCredentials, uniqueName } from "./helpers";

/**
 * Highlight clips of a call (ADR 0033), end to end with the SCRIPTED engine: an agent adds a
 * recording, the worker cleans and writes it out, the agent picks a moment from the transcript
 * (a moment that is too short is refused with a sentence and nothing is made), makes a clip that is
 * first "being cut" and, once the worker ran, ready with its lines as text and a player; edits the
 * title; a manager sees the agent's clip and deletes it after being asked; deleting the recording's
 * audio takes the clips' audio with it and leaves their words. Creates clearly fictional "E2eClips"
 * leads and puts the call-recording switch back.
 *
 * Needs the scripted engine for the API and the worker (CRM_CALLS_ENGINE=fake), the file store
 * running and reachable from the browser, and E2E_CALLS_FAKE=1 here; without it the spec is
 * skipped. Like the other journeys that run the worker itself it expects NO standing worker.
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
  const lastName = uniqueName("E2eClips");
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

// A small file that starts like an mp3; the scripted engine guesses its length from its size
// (one second per 1000 bytes), so this one is "40 seconds" long.
const MP3 = Buffer.concat([
  Buffer.from("ID3\x04\x00\x00\x00\x00\x00\x00", "latin1"),
  Buffer.alloc(40_000, 1),
]);

test("an agent makes a clip from the transcript, a manager deletes it, the audio goes with the recording", async ({
  browser,
}) => {
  test.setTimeout(600_000);
  const admin = await signedIn(browser, USERS.admin, "/automation/agents");
  const wasOn = await setSwitch(admin, true);
  try {
    const agent = await signedIn(browser, USERS.agent1, "/leads/new");
    await newLead(agent);
    const leadUrl = agent.url();

    // 1. A recording, cleaned and written out by the worker.
    await card(agent)
      .getByRole("button", { name: "Add a call recording" })
      .click();
    const dialog = agent.getByRole("dialog");
    await dialog.getByLabel("Recording").setInputFiles({
      name: "clip call.mp3",
      mimeType: "audio/mpeg",
      buffer: MP3,
    });
    await dialog.getByLabel("Language of the call").selectOption("en");
    await dialog.getByRole("checkbox", { name: /buyer agreed/ }).check();
    await dialog.getByRole("button", { name: "Add", exact: true }).click();
    await expect(agent.getByText(/The recording was added/)).toBeVisible();
    runWorkerOnce();
    await agent.reload();
    const call = card(agent)
      .getByTestId("call-item")
      .filter({ hasText: "clip call.mp3" });
    await expect(call.getByTestId("call-status")).toHaveText(
      "Transcript ready",
    );
    await call.getByRole("button", { name: "Show transcript" }).click();
    const clips = call.getByTestId("clips");
    await expect(clips).toContainText("No clips yet.");

    // 2. A moment that is too short is refused next to its field and nothing is made.
    await clips.getByLabel("Start (m:ss)").fill("0:10");
    await clips.getByLabel("End (m:ss)").fill("0:11");
    await clips.getByLabel("Title").fill("Too short");
    await clips.getByRole("button", { name: "Make clip" }).click();
    await expect(clips).toContainText(/at least 3 seconds/);
    await expect(clips).toContainText("No clips yet.");

    // 3. Pick the second transcript line (0:03-0:06) and make the clip; it is first "being cut".
    const second = clips.getByTestId("clip-pick-line").nth(1);
    await second.getByRole("button", { name: "Start here" }).click();
    await second.getByRole("button", { name: "End here" }).click();
    await expect(clips.getByLabel("Start (m:ss)")).toHaveValue("0:03");
    await expect(clips.getByLabel("End (m:ss)")).toHaveValue("0:06");
    await clips.getByLabel("Title").fill("Budget stated");
    await clips.getByLabel("Note (optional)").fill("Ask about the loan");
    await clips.getByRole("button", { name: "Make clip" }).click();
    const clip = clips
      .getByTestId("clip-item")
      .filter({ hasText: "Budget stated" });
    await expect(clip).toContainText("0:03–0:06");
    await expect(clip).toContainText("Being cut");
    await expect(clip.getByRole("button", { name: "Listen" })).toHaveCount(0);
    await expect(clips.getByLabel("Title")).toHaveValue(""); // the form is ready for the next one

    // 4. The worker cuts it; the panel notices by itself and shows its lines and a player.
    runWorkerOnce();
    await expect(clip).toContainText("Ready", { timeout: 30_000 });
    await expect(clip.getByTestId("clip-excerpt")).toContainText(
      "My budget is one point two crore.",
    );
    await expect(clip).toContainText("Ask about the loan");
    await clip.getByRole("button", { name: "Listen" }).click();
    await expect(clip.locator("audio")).toHaveAttribute("src", /^https?:\/\//);

    // 5. The maker edits the title.
    await clip.getByRole("button", { name: "Edit" }).click();
    await clip.getByLabel("Clip title").fill("Budget in crores");
    await clip.getByRole("button", { name: "Save" }).click();
    const renamed = clips
      .getByTestId("clip-item")
      .filter({ hasText: "Budget in crores" });
    await expect(renamed).toBeVisible();

    // 6. A manager sees the clip, is asked before deleting, and deletes it.
    const manager = await signedIn(browser, USERS.manager, leadUrl);
    const theirs = card(manager)
      .getByTestId("call-item")
      .filter({ hasText: "clip call.mp3" });
    await theirs.getByRole("button", { name: "Show transcript" }).click();
    const seen = theirs
      .getByTestId("clip-item")
      .filter({ hasText: "Budget in crores" });
    await expect(seen).toBeVisible();
    await seen.getByRole("button", { name: "Delete" }).click();
    await expect(seen).toContainText("Delete this clip and its audio?");
    await seen.getByRole("button", { name: "Cancel" }).click();
    await expect(seen).toBeVisible();
    await seen.getByRole("button", { name: "Delete" }).click();
    await seen.getByRole("button", { name: "Yes, delete" }).click();
    await expect(theirs.getByTestId("clips")).toContainText("No clips yet.");

    // 7. Make another clip, then delete the recording's audio: the clip's audio goes with it and its
    //    words stay.
    await clips.getByLabel("Start (m:ss)").fill("0:00");
    await clips.getByLabel("End (m:ss)").fill("0:03");
    await clips.getByLabel("Title").fill("Greeting");
    await clips.getByRole("button", { name: "Make clip" }).click();
    await expect(
      clips.getByTestId("clip-item").filter({ hasText: "Greeting" }),
    ).toBeVisible();
    runWorkerOnce();
    await call.getByRole("button", { name: "Delete audio" }).click();
    await agent
      .getByRole("dialog")
      .getByRole("button", { name: "Delete audio" })
      .click();
    await expect(agent.getByText(/The audio was deleted\./)).toBeVisible();
    // The transcript that was open stays open, so the clips are still on the page.
    const kept = call.getByTestId("clip-item").filter({ hasText: "Greeting" });
    await expect(kept).toContainText("The audio was deleted");
    await expect(kept).toContainText(
      "Hello, I am looking for a three bedroom flat",
    );
    await expect(kept.getByRole("button", { name: "Listen" })).toHaveCount(0);
  } finally {
    if (!wasOn) await setSwitch(admin, false);
  }
});

test("a support agent sees no call recordings card and so no clips", async ({
  browser,
}) => {
  const support = await signedIn(browser, USERS.support, "/leads");
  await expect(support.getByTestId("clips")).toHaveCount(0);
});
