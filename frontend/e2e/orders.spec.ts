import { expect, test, type Browser, type Page } from "@playwright/test";

import { USERS, login, requireCredentials, uniqueName } from "./helpers";

/**
 * Phase 12: orders, end to end between the staff CRM and the customer portal.
 * alpha.agent1 owns "Example Customer One Ltd"; alpha.customer1 is linked to it.
 */
test.beforeEach(() => requireCredentials());

async function newPage(browser: Browser, user: string, path = "/") {
  const page = await (await browser.newContext()).newPage();
  await login(page, user, path);
  return page;
}

const orderActions = (page: Page) =>
  page.getByRole("group", { name: "Order actions" });

async function changeStatus(page: Page, button: string, fill?: (dialog: ReturnType<Page["getByRole"]>) => Promise<void>) {
  await orderActions(page).getByRole("button", { name: button }).click();
  const dialog = page.getByRole("dialog", { name: new RegExp(`${button} SO-`) });
  if (fill) await fill(dialog);
  await dialog.getByRole("button", { name: button }).click();
} // prettier-ignore

test("an order goes from a sales draft to delivery, visible to the customer", async ({
  browser,
}) => {
  test.setTimeout(150_000);
  const reference = uniqueName("PO-E2E-");

  // 1. The sales agent creates a draft (validation first) for their own customer.
  const agent = await newPage(browser, USERS.agent1, "/orders/new");
  await agent
    .getByLabel("Customer account")
    .selectOption({ label: "Example Customer One Ltd" });
  await agent.getByRole("button", { name: "Save draft" }).click();
  await expect(agent.getByText("Describe what is ordered.")).toBeVisible();

  await agent.getByLabel("Customer reference").fill(reference);
  const line1 = agent.getByRole("group", { name: "Line 1" });
  await line1.getByLabel("Description").fill("Widget");
  await line1.getByLabel("Quantity").fill("3");
  await line1.getByLabel(/Unit price/).fill("19.99");
  await line1.getByLabel("Tax rate (%)").fill("19");
  await expect(line1.getByText("€71.36")).toBeVisible(); // live preview
  await agent.getByRole("button", { name: "Add line" }).click();
  const line2 = agent.getByRole("group", { name: "Line 2" });
  await line2.getByLabel("Description").fill("Installation");
  await line2.getByLabel("Quantity").fill("1.5");
  await line2.getByLabel(/Unit price/).fill("80");
  await line2.getByLabel("Tax rate (%)").fill("19");
  await agent
    .getByLabel("Internal note")
    .fill("Customer wants delivery before the fair.");
  await agent.getByRole("button", { name: "Save draft" }).click();

  await expect(agent.getByRole("status")).toHaveText(
    "The draft order was saved.",
  );
  await expect(agent.getByText("Not visible to the customer yet.")).toBeVisible();
  await expect(agent.getByText("€214.16").first()).toBeVisible(); // server total
  const staffUrl = new URL(agent.url()).pathname;
  const orderId = staffUrl.split("/").pop() ?? "";
  const number = (await agent.getByRole("heading", { level: 1 }).textContent())?.trim() ?? "";
  expect(number).toMatch(/^SO-\d{4,}$/);

  // 2. The customer cannot see the draft yet.
  const customer = await newPage(browser, USERS.customer, "/portal/orders");
  await expect(customer.getByText(number)).toHaveCount(0);
  await customer.goto(`/portal/orders/${orderId}`);
  await expect(customer.getByRole("heading", { name: "Page not found" })).toBeVisible();

  // 3. The agent edits the draft, then confirms it; agents can't run fulfilment.
  await orderActions(agent).getByRole("link", { name: "Edit draft" }).click();
  await agent.getByRole("button", { name: "Remove line 2" }).click();
  await agent.getByRole("button", { name: "Save changes" }).click();
  await expect(agent.getByRole("status")).toHaveText("The draft order was updated.");
  await expect(agent.getByText("€71.36").first()).toBeVisible();
  await changeStatus(agent, "Confirm order");
  await expect(agent.getByRole("status")).toContainText("The order was confirmed.");
  await expect(orderActions(agent).getByRole("button", { name: "Mark as shipped" })).toHaveCount(0);
  await expect(orderActions(agent).getByRole("link", { name: "Edit draft" })).toHaveCount(0);

  // 4. The customer sees it - without the internal note.
  await customer.goto("/portal/orders");
  await customer.getByRole("link", { name: new RegExp(number) }).click();
  await expect(customer.getByText("Order received").first()).toBeVisible();
  await expect(customer.getByText(reference)).toBeVisible();
  await expect(customer.getByText(/delivery before the fair/)).toHaveCount(0);

  // 5. The manager ships it with a tracking reference and marks it delivered.
  const manager = await newPage(browser, USERS.manager, staffUrl);
  await changeStatus(manager, "Mark as shipped", (d) => d.getByLabel("Tracking reference").fill("DHL 00340434"));
  await expect(manager.getByRole("status")).toHaveText("The order was marked as shipped.");
  await customer.reload();
  await expect(customer.getByText("On its way").first()).toBeVisible();
  await expect(customer.getByText("DHL 00340434")).toBeVisible();
  await changeStatus(manager, "Mark as delivered");
  await expect(manager.getByText("Delivered", { exact: true }).first()).toBeVisible();
  await expect(orderActions(manager)).toHaveCount(0); // final

  // 6. Who else can see it?
  const otherAgent = await newPage(browser, USERS.agent2, staffUrl);
  await expect(otherAgent.getByRole("heading", { name: "Page not found" })).toBeVisible();
  for (const user of ["alpha.customer2", "beta.customer"]) {
    const other = await newPage(browser, user, `/portal/orders/${orderId}`);
    await expect(other.getByRole("heading", { name: "Page not found" })).toBeVisible();
  }
}); // prettier-ignore

test("cancelling asks for a reason that the customer then sees", async ({
  browser,
}) => {
  test.setTimeout(90_000);
  const manager = await newPage(browser, USERS.manager, "/orders/new");
  await manager
    .getByLabel("Customer account")
    .selectOption({ label: "Example Customer One Ltd" });
  const line = manager.getByRole("group", { name: "Line 1" });
  await line.getByLabel("Description").fill("Spare part");
  await line.getByLabel(/Unit price/).fill("5");
  await manager.getByRole("button", { name: "Save draft" }).click();
  await changeStatus(manager, "Confirm order");
  const orderId = new URL(manager.url()).pathname.split("/").pop() ?? "";

  await orderActions(manager).getByRole("button", { name: "Cancel order" }).click();
  const dialog = manager.getByRole("dialog", { name: /Cancel order SO-/ });
  await dialog.getByRole("button", { name: "Cancel order" }).click();
  await expect(dialog.getByText(/Please tell the customer why/)).toBeVisible();
  await dialog.getByLabel(/Reason/).fill("Part is no longer produced.");
  await dialog.getByRole("button", { name: "Cancel order" }).click();
  await expect(manager.getByRole("status")).toHaveText("The order was cancelled.");

  const customer = await newPage(browser, USERS.customer, `/portal/orders/${orderId}`);
  await expect(customer.getByText("This order was cancelled")).toBeVisible();
  await expect(customer.getByText("Reason: Part is no longer produced.")).toBeVisible();
}); // prettier-ignore

test("support can look orders up but not change them; customers never reach staff screens", async ({
  browser,
}) => {
  const support = await newPage(browser, USERS.support, "/orders");
  await expect(support.getByRole("heading", { name: "Orders" })).toBeVisible();
  await expect(support.getByRole("link", { name: "New order" })).toHaveCount(0);
  await support.goto("/orders/new");
  await expect(support.getByText("You don't have access to this page")).toBeVisible();

  const customer = await newPage(browser, USERS.customer, "/orders");
  await expect(customer).toHaveURL("/portal");
}); // prettier-ignore
