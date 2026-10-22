import { expect, test } from "@playwright/test";

import { USERS, login, requireCredentials } from "./helpers";

/** Portal knowledge answers: the customer can ask, and sees cited public help. */
test.beforeEach(() => requireCredentials());

test("a customer asks the portal knowledge base and gets a cited answer", async ({
  page,
}) => {
  await login(page, USERS.customer);

  await page.goto("/portal/knowledge");
  await expect(
    page.getByRole("heading", { level: 1, name: "Help & policies" }),
  ).toBeVisible();

  await page.getByLabel("Your question").fill(
    "How long do customers have to return a damaged item?",
  );
  await page.getByRole("button", { name: "Ask the knowledge base" }).click();

  // The answer must be visible with the exact source passages, never a silent failure.
  const answer = page.getByRole("status").first();
  await expect(answer).toBeVisible({ timeout: 60_000 });
  await expect(answer).toContainText(/14 days|damaged|return/i);
  await expect(page.getByText("Sources used")).toBeVisible({
    timeout: 60_000,
  });
  await expect(page.getByText("Customer returns help")).toBeVisible();
});
