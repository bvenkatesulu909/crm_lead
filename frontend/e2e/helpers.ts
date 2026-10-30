import { expect, test, type Page } from "@playwright/test";

/** Local test identities from infrastructure/keycloak/realm-crm.json (fictional people). */
export const USERS = {
  admin: "alpha.admin",
  agent1: "alpha.agent1",
  agent2: "alpha.agent2",
  manager: "alpha.manager",
  support: "alpha.support",
  customer: "alpha.customer1",
  customer2: "alpha.customer2",
  betaAdmin: "beta.admin",
} as const;

export function requireCredentials() {
  test.skip(
    !process.env.E2E_USER_PASSWORD,
    "E2E_USER_PASSWORD is not set in .env.local",
  );
}

/** Signs in through the real Keycloak login page (Authorization Code + PKCE). */
export async function login(page: Page, username: string, target = "/") {
  // Now and then the Keycloak page does not show its password field (it is slow, or the login
  // session was dropped). Waiting longer does not help, so after a short wait the sign-in is
  // started again, up to three times; a real fault still fails on the last try.
  const ATTEMPTS = 3;
  for (let attempt = 1; ; attempt++) {
    try {
      await page.goto(target);
      await expect(page).toHaveURL(/\/login/);
      await page.getByRole("link", { name: "Sign in" }).click();
      await expect(page).toHaveURL(/localhost:9080\/realms\/crm\//);
      await page.locator("#username").fill(username);
      await page
        .locator("#password")
        .fill(process.env.E2E_USER_PASSWORD ?? "", { timeout: 20_000 });
      await page.locator("#kc-login").click();
      await page.waitForURL(
        (url) =>
          url.origin === "http://localhost:3000" &&
          !url.pathname.startsWith("/login"),
      );
      return;
    } catch (error) {
      if (attempt >= ATTEMPTS) throw error;
      await page.context().clearCookies();
    }
  }
}

export async function signOut(page: Page) {
  await page.getByRole("button", { name: /account menu/i }).click();
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/login\?signed_out=1/);
}

/**
 * Chooses an account in the type-to-search account picker: type part of the name, click the
 * match. Works however many accounts exist (a plain dropdown only lists the first 200).
 */
export async function chooseAccount(page: Page, field: string, name: string) {
  await page.getByRole("combobox", { name: field, exact: true }).fill(name);
  await page.getByRole("option", { name }).click();
}

/** A unique, clearly fictional name so test data never looks like a real customer. */
export function uniqueName(prefix: string) {
  return `${prefix}${Date.now().toString(36).toUpperCase()}`;
}
