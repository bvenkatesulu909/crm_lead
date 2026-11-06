import { expect, test, type Browser, type Page } from "@playwright/test";

import { USERS, login, requireCredentials, uniqueName } from "./helpers";

/**
 * Voice conversation with the staff assistant (ADR 0023), end to end. A test browser has no real
 * voice, so the web app's SCRIPTED speech engine plays the person's spoken questions and records
 * what would have been said aloud; everything else is real: the switch in the agent registry,
 * the streamed answers, the conversation's memory, the approval queue.
 *
 * Needs: CRM_AI_PROVIDER=fake for the API, and E2E_FAKE_ASSISTANT=1 plus
 * NEXT_PUBLIC_VOICE_TEST_ENGINE=1 for the web app (.env.local). Without them it is skipped.
 */
test.beforeEach(() => {
  requireCredentials();
  test.skip(
    !process.env.E2E_FAKE_ASSISTANT ||
      process.env.NEXT_PUBLIC_VOICE_TEST_ENGINE !== "1",
    "needs E2E_FAKE_ASSISTANT=1 and NEXT_PUBLIC_VOICE_TEST_ENGINE=1 (scripted assistant and speech)",
  );
});

type VoiceWindow = Window & {
  __crmVoiceScript?: string[];
  __crmVoiceSpoken?: string[];
};

async function signedIn(
  browser: Browser,
  user: string,
  target = "/",
): Promise<Page> {
  const page = await (await browser.newContext()).newPage();
  await login(page, user, target);
  return page;
}

async function setVoice(browser: Browser, on: boolean) {
  const admin = await signedIn(browser, USERS.admin, "/automation/agents");
  const card = admin.getByRole("article", { name: "Voice conversation" });
  await expect(card).toContainText("server speech");
  const toggle = card.getByLabel("Switched on");
  if ((await toggle.isChecked()) !== on) {
    if (on) await toggle.check();
    else await toggle.uncheck();
    await card.getByRole("button", { name: "Save settings" }).click();
    await expect(admin.getByText(/were saved/)).toBeVisible();
  }
  await admin.context().close();
}

test.afterAll(async ({ browser }) => {
  await setVoice(browser, false); // voice is off by default; leave it that way
});

test("talk to the assistant: answers are spoken, remembered, and changes only proposed", async ({
  browser,
}) => {
  await setVoice(browser, true);
  const agent = await signedIn(browser, USERS.agent1);

  // A fictional lead of this agent.
  const lastName = uniqueName("E2eVoice");
  await agent.goto("/leads/new");
  await agent.getByLabel(/Last name/).fill(lastName);
  await agent.getByRole("button", { name: "Create lead" }).click();
  await agent
    .getByRole("link", { name: new RegExp(lastName) })
    .first()
    .click();
  await agent.waitForURL(/\/leads\/[0-9a-f-]{36}$/);
  const leadId = agent.url().split("/").pop() as string;

  await agent.goto("/assistant");
  // Before the microphone is used, the page says who hears the audio.
  await expect(
    agent.getByText(/Google in Chrome, Apple in Safari/),
  ).toBeVisible();
  await agent.evaluate((id) => {
    (window as VoiceWindow).__crmVoiceScript = [
      "Hello assistant",
      `mark lead ${id} as contacted because they called back today`,
    ];
  }, leadId);
  await agent
    .getByRole("button", { name: "Allow microphone and start" })
    .click();

  const conversation = agent.getByRole("list", { name: "Conversation" });
  await expect(conversation).toContainText("Hello assistant");
  await expect(conversation).toContainText(
    "This demo assistant only understands",
  );
  await expect(conversation).toContainText(`mark lead ${leadId} as contacted`);
  await expect(conversation).toContainText("waiting for a manager's approval");
  await expect(
    agent.getByRole("link", { name: /contacted/i }).first(),
  ).toBeVisible();

  // Nothing more is said: after two silent turns it stops and says so.
  await expect(agent.getByText("I didn't hear anything")).toBeVisible();
  await expect(
    agent.getByRole("button", { name: "Start voice conversation" }),
  ).toBeVisible();

  // What would have been spoken aloud: the answers, sentence by sentence.
  const spoken = await agent.evaluate(
    () => (window as VoiceWindow).__crmVoiceSpoken ?? [],
  );
  expect(spoken.join(" ")).toContain("waiting for a manager's approval");
  expect(spoken.length).toBeGreaterThan(2);

  // A typed follow-up continues the same conversation.
  await agent.getByLabel("Message to the assistant").fill("Thanks");
  await agent.getByRole("button", { name: "Send" }).click();
  await expect(conversation).toContainText("Thanks");
  await expect(
    conversation.getByText(/This demo assistant only understands/),
  ).toHaveCount(2);

  // Nothing changed: the lead is still new, a proposal waits for a manager.
  await agent.goto(`/leads/${leadId}`);
  await expect(agent.getByText("New", { exact: true }).first()).toBeVisible();
  await agent.context().close();

  // Switched off, the voice button is gone.
  await setVoice(browser, false);
  const again = await signedIn(browser, USERS.agent1, "/assistant");
  await expect(
    again.getByRole("heading", { name: "Talk with the assistant" }),
  ).toBeVisible();
  await expect(
    again.getByRole("button", { name: /voice|microphone and start/i }),
  ).toHaveCount(0);
  await again.context().close();
});
