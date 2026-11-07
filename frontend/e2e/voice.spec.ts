import { expect, test } from "@playwright/test";

import { USERS, login, requireCredentials } from "./helpers";

test.beforeEach(() => requireCredentials());
test.use({ permissions: ["microphone"] });

// The staff assistant talks through the live voice conversation (voice-conversation.spec.ts);
// the dictation button that records one question remains in the customer portal.
test("portal assistant records speech and puts the words into the question box", async ({ page }) => {
  await login(page, USERS.customer, "/portal/assistant");
  await page.route("**/api/voice/transcribe", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ text: "Which of my orders are there?" }) }),
  );

  await page.getByRole("button", { name: "Allow microphone" }).click();
  await expect(page.getByText(/Recording \d+s/)).toBeVisible({ timeout: 15_000 });
  await page.getByRole("button", { name: "Stop" }).click();
  // The words land in the box, and the form then sends them on its own: either place counts.
  const question = /Which of my orders are there\?/;
  await expect
    .poll(
      async () =>
        question.test(await page.getByLabel("Your question").inputValue()) ||
        (await page.getByText(question).count()) > 0,
      { timeout: 20_000 },
    )
    .toBe(true);
});
