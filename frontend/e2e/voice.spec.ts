import { expect, test } from "@playwright/test";

import { USERS, login, requireCredentials } from "./helpers";

test.beforeEach(() => requireCredentials());
test.use({ permissions: ["microphone"] });

function silentWav(): Buffer {
  const samples = 8000;
  const buffer = Buffer.alloc(44 + samples * 2);
  buffer.write("RIFF", 0);
  buffer.writeUInt32LE(36 + samples * 2, 4);
  buffer.write("WAVEfmt ", 8);
  buffer.writeUInt32LE(16, 16);
  buffer.writeUInt16LE(1, 20);
  buffer.writeUInt16LE(1, 22);
  buffer.writeUInt32LE(8000, 24);
  buffer.writeUInt32LE(16000, 28);
  buffer.writeUInt16LE(2, 32);
  buffer.writeUInt16LE(16, 34);
  buffer.write("data", 36);
  buffer.writeUInt32LE(samples * 2, 40);
  return buffer;
}

test("staff assistant records speech, transcribes it, and plays server audio", async ({ page }) => {
  await login(page, USERS.admin);
  await page.route("**/api/voice/speak", (route) =>
    route.fulfill({ status: 200, contentType: "audio/wav", body: silentWav() }),
  );
  await page.route("**/api/voice/transcribe", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ text: "Show active customers" }) }),
  );

  await page.goto("/assistant");
  await page.getByLabel("Question").fill("Show active customers");
  await page.getByRole("button", { name: "Ask assistant" }).click();
  await expect(page.getByRole("heading", { name: "Answer" })).toBeVisible({ timeout: 60_000 });

  const speakRequest = page.waitForRequest("**/api/voice/speak");
  await page.getByRole("button", { name: "Listen" }).click();
  await speakRequest;
  await expect(page.getByRole("button", { name: "Stop" })).toBeVisible();
  await page.getByRole("button", { name: "Stop" }).click();

  await page.goto("/assistant");
  await page.getByRole("button", { name: "Allow microphone" }).click();
  await expect(page.getByText(/Recording \d+s/)).toBeVisible({ timeout: 15_000 });
  await page.getByRole("button", { name: "Stop" }).click();
  await expect(page.getByLabel("Question")).toHaveValue(/Show active customers/, {
    timeout: 20_000,
  });
});
