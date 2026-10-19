import { expect, test, type Browser, type Page } from "@playwright/test";

import { USERS, login, requireCredentials, uniqueName } from "./helpers";

/**
 * Phase 14: support tickets, end to end between the customer portal and the staff CRM.
 * customer1 is linked to "Example Customer One Ltd" (owned by alpha.agent1).
 */
test.beforeEach(() => requireCredentials());

async function newPage(browser: Browser, user: string, path = "/") {
  const page = await (await browser.newContext()).newPage();
  await login(page, user, path);
  return page;
}

const ticketActions = (page: Page) =>
  page.getByRole("group", { name: "Ticket actions" });

test("a ticket goes from the customer to support and back", async ({
  browser,
}) => {
  test.setTimeout(120_000);
  const subject = uniqueName("E2eTicket");

  // 1. The customer opens a ticket in the portal (with validation first).
  const customer = await newPage(
    browser,
    USERS.customer,
    "/portal/tickets/new",
  );
  await expect(customer.getByLabel("Account")).toHaveValue(/.+/); // their only account preselected
  await customer.getByLabel("Subject").fill("Hi");
  await customer.getByRole("button", { name: "Submit ticket" }).click();
  await expect(
    customer.getByText("Please give a short subject (at least 3 characters)."),
  ).toBeVisible();
  await customer.getByLabel("Subject").fill(subject);
  await customer
    .getByLabel("Description")
    .fill("The invoice PDF does not open.");
  await customer.getByRole("button", { name: "Submit ticket" }).click();
  await expect(customer.getByRole("status")).toContainText(
    "Your ticket was submitted",
  );
  const portalUrl = new URL(customer.url()).pathname;
  const ticketId = portalUrl.split("/").pop() ?? "";

  // 2. Support finds it, assigns it, writes an internal note and a reply.
  const support = await newPage(browser, USERS.support, "/tickets");
  await support.getByLabel("Search").fill(subject);
  await support.getByRole("button", { name: "Apply" }).click();
  await support.getByRole("link", { name: new RegExp(subject) }).click();
  await expect(support.getByText("SLA on track")).toBeVisible();

  await ticketActions(support).getByRole("button", { name: "Assign" }).click();
  const assign = support.getByRole("dialog", { name: /Assign T-/ });
  await assign
    .getByLabel("Support employee")
    .selectOption({ label: "Casey Support" });
  await assign.getByRole("button", { name: "Assign ticket" }).click();
  await expect(support.getByRole("status")).toHaveText(
    "The ticket was assigned.",
  );

  await support.getByLabel("Internal note (staff only)").check();
  await support
    .getByLabel("Internal note", { exact: true })
    .fill("Check the PDF service logs.");
  await support.getByRole("button", { name: "Add internal note" }).click();
  await expect(
    support.getByText("Internal note — not visible to the customer"),
  ).toBeVisible();

  await support
    .getByLabel("Message to customer")
    .fill("Could you tell us which invoice?");
  await support.getByRole("button", { name: "Send reply to customer" }).click();
  await expect(support.getByRole("status")).toHaveText(
    "Your reply was sent to the customer.",
  );
  await expect(support.getByText("In progress")).toBeVisible(); // first reply opened it

  await ticketActions(support)
    .getByRole("button", { name: "Wait for customer" })
    .click();
  await support
    .getByRole("dialog")
    .getByRole("button", { name: "Wait for customer" })
    .click();
  await expect(support.getByText("Waiting for customer")).toBeVisible();

  // 3. The customer sees the reply - never the internal note - and answers.
  await customer.goto(portalUrl);
  await expect(customer.getByText("Waiting for your reply")).toBeVisible();
  await expect(
    customer.getByText("Could you tell us which invoice?"),
  ).toBeVisible();
  await expect(
    customer.getByText(/PDF service logs|Internal note/),
  ).toHaveCount(0);
  await customer.getByLabel("Your reply").fill("Invoice 2026-104.");
  await customer.getByRole("button", { name: "Send reply" }).click();
  await expect(customer.getByText("We're working on it")).toBeVisible(); // reopened

  // 4. Support resolves and then closes; closing warns that it is final.
  await support.reload();
  await expect(support.getByText("Invoice 2026-104.")).toBeVisible();
  await ticketActions(support).getByRole("button", { name: "Resolve" }).click();
  await support
    .getByRole("dialog")
    .getByRole("button", { name: "Resolve" })
    .click();
  await expect(support.getByText("SLA met")).toBeVisible();
  await ticketActions(support).getByRole("button", { name: "Close" }).click();
  const close = support.getByRole("dialog", { name: /Close T-/ });
  await expect(close).toContainText("A closed ticket is final");
  await close.getByRole("button", { name: "Close" }).click();
  await expect(support.getByText("This ticket is closed.")).toBeVisible();
  await expect(ticketActions(support)).toHaveCount(0);

  await customer.reload();
  await expect(customer.getByText("This ticket is closed.")).toBeVisible();
  await expect(
    customer.getByRole("button", { name: "Send reply" }),
  ).toHaveCount(0);

  // 5. Who else can see it?
  const owner = await newPage(browser, USERS.agent1, `/tickets/${ticketId}`); // owns the account
  await expect(
    owner.getByRole("heading", { level: 1, name: subject }),
  ).toBeVisible();
  await expect(ticketActions(owner)).toHaveCount(0); // read-only for sales
  const otherAgent = await newPage(
    browser,
    USERS.agent2,
    `/tickets/${ticketId}`,
  );
  await expect(
    otherAgent.getByRole("heading", { name: "Page not found" }),
  ).toBeVisible();
  const otherCustomer = await newPage(browser, "alpha.customer2", portalUrl);
  await expect(
    otherCustomer.getByRole("heading", { name: "Page not found" }),
  ).toBeVisible();
  const otherTenant = await newPage(browser, "beta.customer", portalUrl);
  await expect(
    otherTenant.getByRole("heading", { name: "Page not found" }),
  ).toBeVisible();
});

test("staff can open a ticket for a customer after a phone call", async ({
  page,
}) => {
  const subject = uniqueName("E2ePhone");
  await login(page, USERS.support, "/tickets/new");

  await page
    .getByLabel("Account")
    .selectOption({ label: "Example Customer Two Ltd" });
  await page.getByLabel("Priority").selectOption("urgent");
  await page.getByLabel("Subject").fill(subject);
  await page.getByLabel("Description").fill("Customer called: site is down.");
  await page.getByRole("button", { name: "Create ticket" }).click();

  await expect(page.getByRole("status")).toHaveText("The ticket was created.");
  await expect(
    page.getByText("Urgent", { exact: true }).filter({ visible: true }),
  ).toBeVisible();
  await expect(page.getByText("Created by staff")).toBeVisible();
});

test("the portal shows support only for the customer's own company", async ({
  page,
}) => {
  await login(page, "alpha.customer2", "/portal");

  const support = page.getByRole("region", { name: "Support" });
  await expect(support).toBeVisible();
  await page.goto("/portal/tickets");
  await expect(
    page.getByRole("heading", { name: "Support tickets" }),
  ).toBeVisible();
  // Customers never reach the staff ticket screens.
  await page.goto("/tickets");
  await expect(page).toHaveURL("/portal");
});
