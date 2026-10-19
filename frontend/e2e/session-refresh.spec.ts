import { expect, test } from "@playwright/test";

import { USERS, login, requireCredentials } from "./helpers";

/**
 * Slow (about 5 minutes): proves that the 5-minute Keycloak access token is refreshed
 * automatically by proxy.ts, so users are not logged out while working.
 * Run with:  set E2E_SLOW=1 && npx playwright test session-refresh
 */
test("an expiring access token is refreshed without logging the user out", async ({
  page,
  context,
}) => {
  requireCredentials();
  test.skip(!process.env.E2E_SLOW, "slow test: set E2E_SLOW=1 to run");
  test.setTimeout(8 * 60_000);

  await login(page, USERS.agent1, "/leads");
  const before = (await context.cookies()).find(
    (c) => c.name === "crm_session",
  )?.value;

  // Access tokens live 300 s; proxy.ts refreshes when fewer than 30 s are left.
  await page.waitForTimeout(285_000);
  await page.goto("/leads");

  await expect(page).toHaveURL("/leads");
  await expect(page.getByRole("heading", { name: "Leads" })).toBeVisible();
  const after = (await context.cookies()).find(
    (c) => c.name === "crm_session",
  )?.value;
  expect(after).toBeTruthy();
  expect(after).not.toBe(before); // new tokens were stored
});
