import { expect, test } from "@playwright/test";

import { USERS, login, requireCredentials, uniqueName } from "./helpers";

/**
 * Real-estate wishes on leads (ADR 0013, step PC2 / CRM-105), end to end: an agent records a
 * buyer's property type, budget ("1.2 Cr" style) and location, sees them on the lead page, and
 * the budget order is enforced when editing. Creates a clearly fictional "E2eHome…" lead.
 */
test.beforeEach(() => requireCredentials());

test("an agent records a buyer's property wishes on a lead", async ({ page }) => {
  test.setTimeout(90_000);
  const lastName = uniqueName("E2eHome");
  await login(page, USERS.agent1, "/leads/new");

  // A budget that isn't whole rupees is refused in the form, before anything is sent.
  await page.getByLabel(/Last name/).fill(lastName);
  await page.getByLabel(/Minimum budget/).fill("a lot");
  await page.getByRole("button", { name: "Create lead" }).click();
  await expect(page.getByText(/Minimum budget: enter whole rupees/)).toBeVisible();

  await page.getByLabel(/Property type/).selectOption({ label: "Apartment" });
  await page.getByLabel(/Minimum budget/).fill("1.2 Cr");
  await page.getByLabel(/Maximum budget/).fill("1,50,00,000");
  await page.getByLabel(/Location/).fill("Kokapet, Hyderabad");
  await page.getByRole("button", { name: "Create lead" }).click();
  await page.getByRole("link", { name: new RegExp(lastName) }).first().click();

  const details = page.getByRole("main");
  await expect(details).toContainText("Apartment");
  await expect(details).toContainText("₹1.2 Cr – ₹1.5 Cr");
  await expect(details).toContainText("Kokapet, Hyderabad");

  // Editing: a minimum above the maximum is refused; clearing the location works.
  await page.getByRole("link", { name: "Edit", exact: true }).click();
  await expect(page.getByLabel(/Minimum budget/)).toHaveValue("12000000");
  await page.getByLabel(/Minimum budget/).fill("2 Cr");
  await page.getByRole("button", { name: /Save/ }).click();
  await expect(page.getByText("The maximum budget can't be below the minimum budget.")).toBeVisible();
  await page.getByLabel(/Minimum budget/).fill("80 L");
  await page.getByLabel(/Location/).fill("");
  await page.getByRole("button", { name: /Save/ }).click();
  await expect(details).toContainText("₹80 L – ₹1.5 Cr");
  await expect(page.getByRole("term").filter({ hasText: "Location" }).locator("+ dd")).toHaveText("—");
}); // prettier-ignore
