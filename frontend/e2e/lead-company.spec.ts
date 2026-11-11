import { expect, test } from "@playwright/test";

import { USERS, login, requireCredentials, uniqueName } from "./helpers";

/**
 * The company behind a lead (BP-02, ADR 0026 step EN1), end to end: an agent records the
 * company's website, industry and size; the website is stored as https://<host>; a page address
 * is refused; the values show on the lead page. Creates a clearly fictional "E2eCompany…" lead.
 */
test.beforeEach(() => requireCredentials());

test("an agent records the company behind a lead", async ({ page }) => {
  test.setTimeout(90_000);
  const lastName = uniqueName("E2eCompany");
  await login(page, USERS.agent1, "/leads/new");

  const company = page.getByRole("group", { name: "About the company" });
  await page.getByLabel(/Last name/).fill(lastName);
  // A page of the site instead of the site itself is refused before anything is sent.
  await company.getByLabel(/Website/).fill("example-builders.in/about");
  await page.getByRole("button", { name: "Create lead" }).click();
  await expect(page.getByText("Enter only the website's address, like example.com.")).toBeVisible();

  await company.getByLabel(/Website/).fill("Example-Builders.in/");
  await company.getByLabel(/Industry/).selectOption({ label: "Real estate" });
  await company.getByLabel(/Employees/).selectOption({ label: "11-50 employees" });
  await page.getByRole("button", { name: "Create lead" }).click();
  await page.getByRole("link", { name: new RegExp(lastName) }).first().click();

  const term = (name: string) => page.getByRole("term").filter({ hasText: new RegExp(`^${name}$`) }).locator("+ dd");
  await expect(term("Website")).toHaveText("https://example-builders.in");
  await expect(term("Industry")).toHaveText("Real estate");
  await expect(term("Employees")).toHaveText("11-50");

  // Editing: the form shows what is stored; clearing the industry works.
  await page.getByRole("link", { name: "Edit", exact: true }).click();
  await expect(company.getByLabel(/Website/)).toHaveValue("https://example-builders.in");
  await company.getByLabel(/Industry/).selectOption({ label: "Not specified" });
  await page.getByRole("button", { name: /Save/ }).click();
  await expect(term("Industry")).toHaveText("—");
  await expect(term("Employees")).toHaveText("11-50");
}); // prettier-ignore
