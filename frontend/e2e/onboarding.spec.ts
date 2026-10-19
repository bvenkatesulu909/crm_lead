import { expect, test, type Browser, type Page } from "@playwright/test";

import { USERS, login, requireCredentials, uniqueName } from "./helpers";
import {
  linkFromLatestEmail,
  setPasswordFromEmail,
  testPassword,
} from "./mailpit";

/**
 * ADR 0004: people join only through an administrator - invited by e-mail, or after signing
 * up and being approved. All e-mails are read from Mailpit; passwords are set on Keycloak's
 * own pages, never seen by the CRM.
 */
test.beforeEach(() => requireCredentials());

async function newPage(browser: Browser, user?: string, path = "/") {
  const page = await (await browser.newContext()).newPage();
  if (user) await login(page, user, path);
  return page;
}

/** Signs in through Keycloak with a username/e-mail and password (for new people). */
async function signIn(page: Page, username: string, password: string) {
  await page.goto("/login");
  await page.getByRole("link", { name: "Sign in" }).click();
  await page.locator("#username").fill(username);
  await page.locator("#password").fill(password);
  await page.locator("#kc-login").click();
  await page.waitForURL((url) => url.origin === "http://localhost:3000");
}

test("an admin adds a staff member who sets a password and signs in with that role", async ({
  browser,
}) => {
  test.setTimeout(150_000);
  const email = `${uniqueName("staff").toLowerCase()}@example.test`;
  const admin = await newPage(browser, USERS.betaAdmin, "/users");

  await admin.getByRole("button", { name: "Add staff member" }).click();
  const dialog = admin.getByRole("dialog", { name: "Add a staff member" });
  await dialog.getByRole("button", { name: "Add and send invitation" }).click();
  await expect(dialog.getByText("Enter a valid e-mail address.")).toBeVisible();
  await dialog.getByLabel("E-mail").fill(email);
  await dialog.getByLabel("First name").fill("Riley");
  await dialog.getByLabel("Last name").fill("Newhire");
  await dialog.getByLabel("Role").selectOption("support_agent");
  await dialog.getByRole("button", { name: "Add and send invitation" }).click();
  await expect(admin.getByRole("status")).toContainText("The staff member was added");
  const rileyRow = admin.getByRole("row").filter({ hasText: email });
  await expect(rileyRow).toContainText("Support Agent");

  // The invitation arrives; Riley chooses a password on Keycloak's page.
  const password = testPassword();
  const person = await newPage(browser);
  await setPasswordFromEmail(person, await linkFromLatestEmail(email), password);
  await signIn(person, email, password);
  await expect(person.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Support" })).toBeVisible();
  await expect(person.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Users" })).toHaveCount(0);

  // Deactivating locks Riley out.
  await admin.reload();
  const row = admin.getByRole("row").filter({ hasText: email }).getByRole("group");
  await row.getByRole("button", { name: "Deactivate" }).click();
  await admin.getByRole("dialog", { name: /Deactivate Riley/ }).getByRole("button", { name: "Deactivate" }).click();
  await expect(admin.getByRole("status")).toContainText("deactivated");
  await person.goto("/");
  await expect(person).toHaveURL(/\/pending/);
  await expect(person.getByText(/Your account has been deactivated/)).toBeVisible();
}); // prettier-ignore

test("someone signs up, waits with the code, gets approved as a customer and sees only that account", async ({
  browser,
}) => {
  test.setTimeout(300_000);
  const email = `${uniqueName("signup").toLowerCase()}@example.test`;
  const password = testPassword();

  // 1. The admin reads the organisation's sign-up code.
  const admin = await newPage(browser, USERS.betaAdmin, "/users");
  const code = (await admin.locator('p[aria-label="Sign-up code"]').textContent())?.trim() ?? "";
  expect(code).toMatch(/^[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}$/);

  // 2. A new person creates an account on the login page and verifies the e-mail.
  const person = await newPage(browser);
  await person.goto("/login");
  await person.getByRole("link", { name: "Create an account" }).click();
  await person.locator("#firstName").fill("Casey");
  await person.locator("#lastName").fill("Signup");
  await person.locator("#email").fill(email);
  if (await person.locator("#username").isVisible()) await person.locator("#username").fill(email);
  await person.locator("#password").fill(password);
  await person.locator("#password-confirm").fill(password);
  await person.locator("input[type=submit], button[type=submit]").first().click();
  await person.goto(await linkFromLatestEmail(email));
  if (!person.url().startsWith("http://localhost:3000")) {
    const back = person.getByRole("link", { name: /back to application|proceed/i });
    if (await back.isVisible().catch(() => false)) await back.click();
  }
  if (!person.url().startsWith("http://localhost:3000")) await signIn(person, email, password);

  // 3. No CRM data, only the waiting page. A wrong code is refused.
  await person.goto("/");
  await expect(person).toHaveURL(/\/pending/);
  await person.getByLabel("Organisation sign-up code").fill("AAAA-BBBB-CCCC");
  await person.getByRole("button", { name: "Request access" }).click();
  await expect(person.getByText(/This code is not valid/)).toBeVisible();
  await person.getByLabel("Organisation sign-up code").fill(code.toLowerCase());
  await person.getByRole("button", { name: "Request access" }).click();
  await expect(person.getByRole("status")).toContainText("Your request to join");
  await person.goto("/portal");
  await expect(person).toHaveURL(/\/pending/);

  // 4. The admin approves as a customer of one account.
  await admin.reload();
  const requests = admin.getByRole("list", { name: "Access requests" });
  await requests.getByRole("listitem").filter({ hasText: email }).getByRole("button", { name: "Approve" }).click();
  const approve = admin.getByRole("dialog", { name: "Approve Casey Signup" });
  await approve.getByLabel("Role").selectOption("customer");
  await approve.getByRole("button", { name: "Approve" }).click();
  await expect(approve.getByText(/Choose at least one account/)).toBeVisible();
  await approve.getByLabel("Example Customer Three Ltd").check();
  await approve.getByRole("button", { name: "Approve" }).click();
  await expect(admin.getByRole("status")).toHaveText("The request was approved.");

  // 5. Casey continues into the portal and sees exactly that account.
  await person.goto("/pending");
  await person.getByRole("button", { name: "Continue to crm-lead" }).click();
  await expect(person).toHaveURL(/\/portal/);
  const accounts = person.getByRole("region", { name: "Your accounts" });
  await expect(accounts.getByRole("link")).toHaveText([/Example Customer Three Ltd/]);
}); // prettier-ignore

test("a sales agent invites a customer contact for their own account only", async ({
  browser,
}) => {
  test.setTimeout(150_000);
  const email = `${uniqueName("contact").toLowerCase()}@example.test`;
  const agent = await newPage(browser, USERS.agent1, "/accounts?q=example+customer+one");
  await agent.getByRole("link", { name: "Example Customer One Ltd" }).click();

  await agent.getByRole("button", { name: "Invite" }).click();
  const dialog = agent.getByRole("dialog", { name: /Invite a contact/ });
  await dialog.getByLabel("E-mail").fill(email);
  await dialog.getByLabel("First name").fill("Jo");
  await dialog.getByLabel("Last name").fill("Contact");
  await dialog.getByRole("button", { name: "Send invitation" }).click();
  await expect(agent.getByRole("status")).toContainText("The invitation was sent");
  await expect(agent.getByText(`${email} · invited, not signed in yet`)).toBeVisible();

  const password = testPassword();
  const contact = await newPage(browser);
  await setPasswordFromEmail(contact, await linkFromLatestEmail(email), password);
  await signIn(contact, email, password);
  await contact.goto("/portal");
  await expect(contact.getByRole("region", { name: "Your accounts" }).getByRole("link")).toHaveText([/Example Customer One Ltd/]);

  // Another agent's account offers no invitation (and the API would refuse it anyway).
  const other = await newPage(browser, USERS.agent2, "/accounts?q=example+customer+two");
  await other.getByRole("link", { name: "Example Customer Two Ltd" }).click();
  await expect(other.getByRole("heading", { name: "Portal access" })).toBeVisible();
  await agent.goto("/users");
  await expect(agent.getByText("You don't have access to this page")).toBeVisible();
}); // prettier-ignore
