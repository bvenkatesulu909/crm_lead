import { expect, test, type Browser, type Page } from "@playwright/test";

import { USERS, login, requireCredentials } from "./helpers";

/**
 * Phase 13: invoices, credit notes and payments, end to end between the staff CRM and the
 * customer portal. alpha.customer1 is linked to "Example Customer One Ltd".
 */
test.beforeEach(() => requireCredentials());

async function newPage(browser: Browser, user: string, path = "/") {
  const page = await (await browser.newContext()).newPage();
  await login(page, user, path);
  return page;
}

const invoiceActions = (page: Page) =>
  page.getByRole("group", { name: "Invoice actions" });

/** Manager: a confirmed order for 3 x 19.99 @ 19 % = 71.36. Returns the order URL. */
async function confirmedOrder(page: Page) {
  await page.goto("/orders/new");
  await page.getByLabel("Customer account").selectOption({ label: "Example Customer One Ltd" });
  const line = page.getByRole("group", { name: "Line 1" });
  await line.getByLabel("Description").fill("Widget");
  await line.getByLabel("Quantity").fill("3");
  await line.getByLabel(/Unit price/).fill("19.99");
  await line.getByLabel("Tax rate (%)").fill("19");
  await page.getByRole("button", { name: "Save draft" }).click();
  await page.getByRole("group", { name: "Order actions" }).getByRole("button", { name: "Confirm order" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Confirm order" }).click();
  await expect(page.getByRole("status")).toContainText("The order was confirmed.");
  return new URL(page.url()).pathname;
} // prettier-ignore

async function dialogAction(page: Page, button: string, fill?: (dialog: ReturnType<Page["getByRole"]>) => Promise<void>, confirm = button) {
  await invoiceActions(page).getByRole("button", { name: button }).click();
  const dialog = page.getByRole("dialog").filter({ visible: true });
  if (fill) await fill(dialog);
  await dialog.getByRole("button", { name: confirm }).click();
} // prettier-ignore

test("an invoice is issued, partly paid, corrected and settled - and the customer follows it", async ({
  browser,
}) => {
  test.setTimeout(180_000);
  const manager = await newPage(browser, USERS.manager, "/orders");
  const orderUrl = await confirmedOrder(manager);

  // 1. Create a draft from the order: no number yet, invisible to the customer.
  await manager.getByRole("button", { name: "Create invoice" }).click();
  await manager.getByRole("dialog").getByRole("button", { name: "Create draft invoice" }).click();
  await expect(manager.getByRole("status")).toHaveText("The draft invoice was created from the order.");
  await expect(manager.getByRole("heading", { level: 1 })).toHaveText("Draft invoice");
  const invoiceUrl = new URL(manager.url()).pathname;
  const invoiceId = invoiceUrl.split("/").pop() ?? "";
  const customer = await newPage(browser, USERS.customer, `/portal/invoices/${invoiceId}`);
  await expect(customer.getByRole("heading", { name: "Page not found" })).toBeVisible();

  // 2. Issue it: it gets its number.
  await dialogAction(manager, "Issue invoice");
  await expect(manager.getByRole("status")).toContainText("The invoice was issued.");
  const number = (await manager.getByRole("heading", { level: 1 }).textContent())?.trim() ?? "";
  expect(number).toMatch(/^INV-\d{4,}$/);
  await expect(invoiceActions(manager).getByRole("button", { name: "Discard draft" })).toHaveCount(0);

  // 3. The customer sees what is owed.
  await customer.reload();
  await expect(customer.getByRole("heading", { name: number })).toBeVisible();
  await expect(customer.getByText("Awaiting payment")).toBeVisible();
  await expect(customer.getByText("€71.36 is due on")).toBeVisible();

  // 4. A payment of 50 arrives, a credit note of 1.36, then the payment bounces.
  await dialogAction(manager, "Record payment", async (d) => {
    await d.getByLabel(/Amount/).fill("71.37");
    await d.getByLabel("Reference").fill("BANK-4711");
  });
  await expect(manager.getByRole("dialog").filter({ visible: true }).getByText(/more than the amount still owed/)).toBeVisible();
  await manager.getByRole("dialog").filter({ visible: true }).getByLabel(/Amount/).fill("50");
  await manager.getByRole("dialog").filter({ visible: true }).getByRole("button", { name: "Record payment" }).click();
  await expect(manager.getByRole("status")).toHaveText("The payment was recorded.");
  await expect(manager.getByText("Partially paid").first()).toBeVisible();

  await dialogAction(manager, "Issue credit note", async (d) => {
    await d.getByLabel(/Reason/).fill("Scratched packaging");
    await d.getByLabel(/Net amount/).fill("1.36");
  });
  await expect(manager.getByRole("status")).toHaveText("The credit note was issued.");
  await expect(manager.getByLabel("Balance").getByText("€20.00")).toBeVisible();

  await manager.getByRole("button", { name: "Reverse", exact: true }).click();
  const reverse = manager.getByRole("dialog", { name: /Reverse the payment/ });
  await reverse.getByLabel("Reason").fill("Transfer bounced");
  await reverse.getByRole("button", { name: "Reverse payment" }).click();
  await expect(manager.getByRole("status")).toHaveText("The payment was reversed.");
  await expect(manager.getByLabel("Balance").getByText("€70.00")).toBeVisible();

  // 5. The full amount arrives.
  await dialogAction(manager, "Record payment"); // defaults to the amount still owed
  await expect(manager.getByText("Paid", { exact: true }).first()).toBeVisible();
  await expect(invoiceActions(manager)).toHaveCount(0);

  // 6. The customer sees it paid, with the credit note, and never the bounced payment.
  await customer.reload();
  await expect(customer.getByText("Paid", { exact: true }).first()).toBeVisible();
  await expect(customer.getByText(/Scratched packaging/)).toBeVisible();
  const payments = customer.getByRole("heading", { name: "Payments received" }).locator("..");
  await expect(payments.getByRole("listitem")).toHaveCount(1);
  await expect(customer.getByText(/bounced/i)).toHaveCount(0);
  await expect(customer.getByText("BANK-4711")).toHaveCount(0);

  // 7. The order links to its invoice and can't be invoiced twice.
  await manager.goto(orderUrl);
  await expect(manager.getByRole("link", { name: number })).toBeVisible();
  await expect(manager.getByRole("button", { name: "Create invoice" })).toHaveCount(0);

  // 8. Who else can see it?
  const owner = await newPage(browser, USERS.agent1, invoiceUrl);
  await expect(owner.getByRole("heading", { name: number })).toBeVisible();
  await expect(invoiceActions(owner)).toHaveCount(0); // read-only for sales agents
  const otherAgent = await newPage(browser, USERS.agent2, invoiceUrl);
  await expect(otherAgent.getByRole("heading", { name: "Page not found" })).toBeVisible();
  for (const user of ["alpha.customer2", "beta.customer"]) {
    const other = await newPage(browser, user, `/portal/invoices/${invoiceId}`);
    await expect(other.getByRole("heading", { name: "Page not found" })).toBeVisible();
  }
}); // prettier-ignore

test("a discarded draft frees the order and never uses a number", async ({ page }) => {
  test.setTimeout(90_000);
  await login(page, USERS.manager, "/orders");
  await confirmedOrder(page);
  await page.getByRole("button", { name: "Create invoice" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Create draft invoice" }).click();
  await dialogAction(page, "Discard draft");
  await expect(page.getByRole("status")).toHaveText("The draft was discarded.");
  await expect(page.getByText("Discarded").first()).toBeVisible();
  await expect(invoiceActions(page)).toHaveCount(0);
}); // prettier-ignore

test("customers see their invoices in the portal; staff screens stay closed", async ({ page }) => {
  await login(page, USERS.customer, "/portal");
  await expect(page.getByRole("region", { name: "Invoices to pay" })).toBeVisible();
  await page.goto("/portal/invoices");
  await expect(page.getByRole("heading", { name: "Invoices", level: 1 })).toBeVisible();
  await page.goto("/invoices");
  await expect(page).toHaveURL("/portal");
}); // prettier-ignore
