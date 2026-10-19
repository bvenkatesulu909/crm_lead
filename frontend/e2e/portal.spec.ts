import { expect, test } from "@playwright/test";

import { USERS, login, requireCredentials } from "./helpers";

/**
 * Customer portal (Phase 15) - permitted and forbidden scenarios against the running backend.
 * Seed data (scripts/seed_dev_data.py): customer1 -> account A1, customer2 -> A2 (same tenant),
 * beta.customer -> B1 (other tenant).
 */
test.beforeEach(() => requireCredentials());

const A1 = "ac000000-0000-4000-8000-0000000000a1";
const A2 = "ac000000-0000-4000-8000-0000000000a2";
const B1 = "ac000000-0000-4000-8000-0000000000b1";

test("a customer lands in the portal and sees only their own account", async ({
  page,
}) => {
  await login(page, USERS.customer);

  await expect(page).toHaveURL("/portal");
  await expect(
    page.getByRole("heading", { name: "Welcome, Dana" }),
  ).toBeVisible();
  await expect(page.getByText("Alpha Demo (fictional)")).toBeVisible(); // whose portal this is
  const accounts = page.getByRole("region", { name: "Your accounts" });
  await expect(accounts.getByRole("link")).toHaveCount(1);
  await expect(accounts.getByRole("link")).toContainText(
    "Example Customer One Ltd",
  );
  await expect(page.getByText("Example Customer Two Ltd")).toHaveCount(0);

  await accounts.getByRole("link").click();
  await expect(
    page.getByRole("heading", { level: 1, name: "Example Customer One Ltd" }),
  ).toBeVisible();
  // Customer-safe fields only: no owner, account number or internal data.
  await expect(page.getByText(/Owner|Account number|Avery Agent/)).toHaveCount(
    0,
  );
  // Orders and invoices are still to come; support tickets are real now.
  await expect(page.getByText("Coming soon to the portal.")).toHaveCount(0);
  await expect(page.getByRole("region", { name: "Invoices" })).toBeVisible();
  await expect(page.getByRole("region", { name: "Orders" })).toBeVisible();
  await expect(
    page.getByRole("region", { name: "Support tickets" }),
  ).toBeVisible();
});

test("a customer cannot open another customer's account, in any tenant", async ({
  page,
}) => {
  await login(page, USERS.customer);

  for (const other of [A2, B1]) {
    await page.goto(`/portal/accounts/${other}`);
    await expect(
      page.getByRole("heading", { name: "Page not found" }),
    ).toBeVisible();
    await expect(page.getByText(/Example Customer (Two|Three)/)).toHaveCount(0);
  }
  await page.goto("/portal/accounts/not-a-uuid");
  await expect(
    page.getByRole("heading", { name: "Page not found" }),
  ).toBeVisible();
});

test("customers of the other tenant see only their own company", async ({
  page,
}) => {
  await login(page, "beta.customer");

  const accounts = page.getByRole("region", { name: "Your accounts" });
  await expect(accounts.getByRole("link")).toHaveText([
    /Example Customer Three Ltd/,
  ]);
  await page.goto(`/portal/accounts/${A1}`);
  await expect(
    page.getByRole("heading", { name: "Page not found" }),
  ).toBeVisible();
});

test("customers are kept out of the staff CRM", async ({ page }) => {
  await login(page, USERS.customer);

  for (const path of [
    "/",
    "/leads",
    "/accounts",
    `/accounts/${A1}`,
    "/profile",
  ]) {
    await page.goto(path);
    await expect(page).toHaveURL("/portal");
  }
});

test("staff are told the portal is for customers", async ({ page }) => {
  await login(page, USERS.agent1);

  await page.goto("/portal");
  await expect(page.getByText("This area is for customers")).toBeVisible();
  await expect(page.getByRole("region", { name: "Your accounts" })).toHaveCount(
    0,
  );
  await page.getByRole("link", { name: "Go to the CRM" }).click();
  await expect(page).toHaveURL("/");
});

test("the portal account menu signs the customer out", async ({
  page,
  context,
}) => {
  await login(page, USERS.customer);

  await page.getByRole("button", { name: /account menu/i }).click();
  await expect(page.getByRole("link", { name: "Your profile" })).toHaveCount(0); // staff-only page
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/login\?signed_out=1/);
  expect((await context.cookies()).some((c) => c.name === "crm_session")).toBe(
    false,
  );
});
