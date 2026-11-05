import { expect, test, type Page } from "@playwright/test";

import { USERS, login, requireCredentials } from "./helpers";

/**
 * The RERA refusal gate on screen (CRM-115 / BP-08, step BR4, docs/brochures-rera.md): a RERA
 * number that is in no document the person may see is refused BEFORE any model is called, and the
 * page says why in plain words - for staff and for a portal customer. No paid model is needed.
 * DEMO-P02499999999 is a fictional number that no seeded brochure carries.
 */
test.beforeEach(() => requireCredentials());

const UNKNOWN = "DEMO-P02499999999";

async function ask(page: Page, question: string) {
  await page.getByLabel("Your question").fill(question);
  await page.getByRole("button", { name: "Ask the knowledge base" }).click();
}

test("staff asking about an unknown RERA number are told to check the number", async ({
  page,
}) => {
  await login(page, USERS.agent1, "/knowledge/search");
  await ask(page, `Is ${UNKNOWN} registered?`);
  const answer = page.getByRole("status").first();
  await expect(answer).toContainText(`couldn't find RERA number ${UNKNOWN}`);
  await expect(answer).toContainText(/Check the number/);
  await expect(answer).not.toContainText(/close enough/);
  await expect(page.getByText("Sources used")).toHaveCount(0);
});

test("a customer gets the same plain refusal in the portal", async ({ page }) => {
  await login(page, USERS.customer, "/portal/knowledge");
  await ask(page, `What does ${UNKNOWN} cost?`);
  const answer = page.getByRole("status").first();
  await expect(answer).toContainText(`couldn't find RERA number ${UNKNOWN}`);
  await expect(page.getByText("Sources used")).toHaveCount(0);
});
