import { expect, test, type Page } from "@playwright/test";

import { USERS, login, requireCredentials, uniqueName } from "./helpers";

/**
 * Workflow 2: lead details, edit, assign, qualify/disqualify, convert - against the running
 * backend. Creates clearly fictional "E2e…" leads in the local development database.
 */
test.beforeEach(() => requireCredentials());

async function createLead(
  page: Page,
  lastName: string,
  company?: string,
): Promise<string> {
  await page.goto("/leads/new");
  await page.getByLabel(/Last name/).fill(lastName);
  if (company) await page.getByLabel(/Company/).fill(company);
  await page.getByRole("button", { name: "Create lead" }).click();
  await expect(page).toHaveURL(/created=/);
  await page.getByRole("link", { name: new RegExp(lastName) }).click();
  await expect(
    page.getByRole("heading", { level: 1, name: new RegExp(lastName) }),
  ).toBeVisible();
  return new URL(page.url()).pathname;
}

const actions = (page: Page) =>
  page.getByRole("group", { name: "Lead actions" });

test("a manager assigns a lead after confirming; ownership and access follow", async ({
  browser,
}) => {
  const lastName = uniqueName("E2eAssign");
  const manager = await (await browser.newContext()).newPage();
  await login(manager, USERS.manager);
  const leadUrl = await createLead(manager, lastName);

  // Opening the dialog and cancelling changes nothing.
  await actions(manager).getByRole("button", { name: "Assign" }).click();
  const dialog = manager.getByRole("dialog", { name: "Assign this lead" });
  await expect(dialog).toContainText("is owned by Morgan Manager");
  await dialog.getByRole("button", { name: "Cancel" }).click();
  await expect(dialog).toBeHidden();

  // Confirming without choosing shows a field error from the server-side check.
  await actions(manager).getByRole("button", { name: "Assign" }).click();
  await dialog.getByRole("button", { name: "Assign lead" }).click();
  await expect(
    dialog.getByText("Choose who should own this lead."),
  ).toBeVisible();

  await dialog.getByLabel("New owner").selectOption({ label: "Blake Agent" });
  await dialog.getByLabel(/Reason/).fill("Territory change");
  await dialog.getByRole("button", { name: "Assign lead" }).click();

  await expect(manager.getByRole("status")).toHaveText(
    "The lead was assigned.",
  );
  await expect(manager.getByText("Owner: Blake Agent")).toBeVisible();
  const history = manager
    .getByRole("heading", { name: "Ownership history" })
    .locator("..");
  await expect(history).toContainText("Morgan Manager → Blake Agent");
  await expect(history).toContainText("Territory change");

  // The new owner can open it; another agent gets "not found" from the API.
  const agent2 = await (await browser.newContext()).newPage();
  await login(agent2, USERS.agent2, leadUrl);
  await expect(
    agent2.getByRole("heading", { level: 1, name: new RegExp(lastName) }),
  ).toBeVisible();
  const agent1 = await (await browser.newContext()).newPage();
  await login(agent1, USERS.agent1, leadUrl);
  await expect(
    agent1.getByRole("heading", { name: "Page not found" }),
  ).toBeVisible();
});

test("an agent edits, qualifies and converts a lead", async ({ page }) => {
  const lastName = uniqueName("E2eConvert");
  const company = `${lastName} Fictional Ltd`;
  await login(page, USERS.agent1);
  const leadUrl = await createLead(page, lastName, company);

  // Edit
  await actions(page).getByRole("link", { name: "Edit" }).click();
  await page.getByLabel(/Phone/).fill("+44 20 7946 0000");
  await page.getByRole("button", { name: "Save changes" }).click();
  await expect(page.getByRole("status")).toHaveText("The lead was updated.");
  await expect(page.getByText("+44 20 7946 0000")).toBeVisible();

  // Qualify (with confirmation)
  await actions(page)
    .getByRole("button", { name: "Qualify", exact: true })
    .click();
  const qualify = page.getByRole("dialog", { name: "Qualify this lead?" });
  await qualify.getByLabel(/Note/).fill("Budget confirmed");
  await qualify.getByRole("button", { name: "Qualify lead" }).click();
  await expect(page.getByRole("status")).toHaveText("The lead was qualified.");
  await expect(
    page.getByText("Status changed from new to qualified"),
  ).toBeVisible();

  // Convert (with confirmation, warning and opportunity)
  await actions(page).getByRole("button", { name: "Convert" }).click();
  const convert = page.getByRole("dialog", { name: "Convert this lead" });
  await expect(convert).toContainText("This cannot be undone.");
  await convert.getByLabel(/Amount/).fill("12,50"); // invalid on purpose
  await convert.getByRole("button", { name: "Convert lead" }).click();
  await expect(
    convert.getByText("Enter an amount like 1250 or 1250.50."),
  ).toBeVisible();
  await convert.getByLabel(/Amount/).fill("1250.50");
  await convert.getByRole("button", { name: "Convert lead" }).click();

  await expect(page.getByRole("status")).toHaveText("The lead was converted.");
  const converted = page
    .getByRole("heading", { name: "Converted" })
    .locator("..");
  await expect(converted).toContainText(company); // the new account, named after the company
  await expect(converted).toContainText("Created"); // opportunity
  await expect(actions(page)).toHaveCount(0); // read-only now

  // Even the edit URL refuses.
  await page.goto(`${leadUrl}/edit`);
  await expect(
    page.getByText("A converted lead can no longer be changed."),
  ).toBeVisible();
});

test("two people editing the same lead: the second save is refused, not silently lost", async ({
  browser,
}) => {
  const lastName = uniqueName("E2eVersion");
  const context = await browser.newContext();
  const first = await context.newPage();
  await login(first, USERS.agent1);
  const leadUrl = await createLead(first, lastName);
  const second = await context.newPage();

  await first.goto(`${leadUrl}/edit`);
  await second.goto(`${leadUrl}/edit`);
  await first.getByLabel(/Job title/).fill("CTO");
  await first.getByRole("button", { name: "Save changes" }).click();
  await expect(first.getByRole("status")).toHaveText("The lead was updated.");

  await second.getByLabel(/Job title/).fill("CEO");
  await second.getByRole("button", { name: "Save changes" }).click();
  const error = second
    .getByRole("alert")
    .filter({ hasText: "Your changes could not be saved" });
  await expect(error).toContainText("changed by someone else");
  await expect(second.getByLabel(/Job title/)).toHaveValue("CEO"); // typing kept
});

test("disqualifying needs a reason, and only valid next steps are offered", async ({
  page,
}) => {
  await login(page, USERS.agent1);
  await createLead(page, uniqueName("E2eDisq"));

  await actions(page).getByRole("button", { name: "Disqualify" }).click();
  const dialog = page.getByRole("dialog", { name: "Disqualify this lead?" });
  await dialog.getByRole("button", { name: "Disqualify lead" }).click();
  await expect(
    dialog.getByText("Please say why this lead is not a fit."),
  ).toBeVisible();
  await dialog.getByLabel("Reason").fill("No budget this year");
  await dialog.getByRole("button", { name: "Disqualify lead" }).click();

  await expect(page.getByRole("status")).toHaveText(
    "The lead was disqualified.",
  );
  await expect(page.getByText("No budget this year")).toBeVisible();
  // unqualified -> qualified is not allowed by the backend, so it isn't offered.
  await expect(
    actions(page).getByRole("button", { name: "Qualify", exact: true }),
  ).toHaveCount(0);
  await expect(
    actions(page).getByRole("button", { name: "Mark as contacted" }),
  ).toBeVisible();
});

test("another tenant cannot open the lead, and bad IDs are simply not found", async ({
  browser,
}) => {
  const owner = await (await browser.newContext()).newPage();
  await login(owner, USERS.agent1);
  const leadUrl = await createLead(owner, uniqueName("E2eTenant"));

  const beta = await (await browser.newContext()).newPage();
  await login(beta, USERS.betaAdmin, leadUrl);
  await expect(
    beta.getByRole("heading", { name: "Page not found" }),
  ).toBeVisible();
  await beta.goto("/leads/not-a-uuid");
  await expect(
    beta.getByRole("heading", { name: "Page not found" }),
  ).toBeVisible();
});

test("dialogs work with the keyboard: Enter opens, Escape cancels, focus returns", async ({
  page,
}) => {
  await login(page, USERS.agent1);
  await createLead(page, uniqueName("E2eKeys"));

  const qualify = actions(page).getByRole("button", {
    name: "Qualify",
    exact: true,
  });
  await qualify.focus();
  await page.keyboard.press("Enter");
  const dialog = page.getByRole("dialog", { name: "Qualify this lead?" });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByLabel(/Note/)).toBeFocused(); // focus moved into the dialog

  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
  await expect(qualify).toBeFocused();
  await expect(page.getByText("New", { exact: true }).first()).toBeVisible(); // nothing changed
});
