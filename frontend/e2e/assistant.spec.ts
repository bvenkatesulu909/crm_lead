import { expect, test } from "@playwright/test";

import { USERS, login, requireCredentials } from "./helpers";

/**
 * Phase 20a: the customer assistant. Without CRM_ANTHROPIC_API_KEY in backend/.env the portal
 * must say honestly that it isn't available (and offer a ticket). With a key, a real Claude
 * conversation runs: an order question, and a hand-over that only the customer can confirm.
 */
test.beforeEach(() => requireCredentials());

test("the portal offers the assistant and is honest when it is not available", async ({
  page,
}) => {
  await login(page, USERS.customer, "/portal");
  await page
    .getByRole("region", { name: "Assistant" })
    .getByRole("link", { name: "Ask the assistant" })
    .click();
  await expect(
    page.getByRole("heading", { level: 1, name: "Assistant" }),
  ).toBeVisible();
  await expect(
    page.getByText(/It only sees your company.s data/),
  ).toBeVisible();

  const unavailable = page.getByText(
    "The assistant is not available right now",
  );
  if (await unavailable.isVisible()) {
    await expect(
      page.getByRole("link", { name: "Open a ticket" }),
    ).toBeVisible();
  } else {
    await expect(page.getByLabel("Your question")).toBeVisible();
  }
});

test("staff never reach the customer assistant", async ({ page }) => {
  await login(page, USERS.support, "/portal/assistant");
  await expect(page.getByText("This area is for customers")).toBeVisible();
});

test("LIVE: the assistant answers from the customer's data and hands over only after confirmation", async ({
  page,
}) => {
  test.setTimeout(180_000);
  await login(page, USERS.customer, "/portal/assistant");
  test.skip(
    await page.getByText("The assistant is not available right now").isVisible(),
    "No CRM_ANTHROPIC_API_KEY configured in backend/.env",
  );

  const conversation = page.getByRole("list", { name: "Conversation" });
  await page.getByLabel("Your question").fill("Which of my orders are there?");
  await page.getByRole("button", { name: "Send" }).click();
  await expect(conversation.getByRole("listitem")).toHaveCount(2, { timeout: 90_000 });
  await expect(conversation).not.toContainText("Example Customer Two Ltd");

  await page
    .getByLabel("Your question")
    .fill("I'd like a refund for a broken widget. Please hand this to your team.");
  await page.getByRole("button", { name: "Send" }).click();
  const prepared = page.getByRole("group", { name: "Prepared support ticket" });
  await expect(prepared).toBeVisible({ timeout: 90_000 });
  await expect(prepared).toContainText("Hand over to our support team?");
  await prepared.getByRole("button", { name: "Create ticket" }).click();
  await expect(prepared).toContainText(/Ticket T-\d{4} created/);
}); // prettier-ignore
