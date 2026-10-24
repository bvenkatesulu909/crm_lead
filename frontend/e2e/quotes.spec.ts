import { execFileSync } from "node:child_process";
import { readFile } from "node:fs/promises";
import path from "node:path";

import { expect, test, type Browser, type Page } from "@playwright/test";

import { USERS, login, requireCredentials, uniqueName, chooseAccount } from "./helpers";
import { latestMessageTo } from "./mailpit";

/**
 * Phase E1: catalogue, price books and quotes with approval, end to end.
 * The manager adds a product and its price; the agent quotes it with a 15 % discount (needs
 * approval); the manager approves; the agent sends; the customer accepts in the portal; the
 * agent turns the quote into a draft order. Creates clearly fictional "E2E…" records.
 * alpha.agent1 owns "Example Customer One Ltd"; alpha.customer1 is linked to it.
 */
test.beforeEach(() => requireCredentials());

async function signedIn(browser: Browser, user: string, target = "/") {
  const page = await (await browser.newContext()).newPage();
  await login(page, user, target);
  return page;
}

const quoteActions = (page: Page) =>
  page.getByRole("group", { name: "Quote actions" });

async function downloadPdf(page: Page) {
  const [download] = await Promise.all([
    page.waitForEvent("download"),
    page.getByRole("link", { name: "Download PDF" }).click(),
  ]);
  const path = await download.path();
  return { name: download.suggestedFilename(), bytes: await readFile(path) };
}

async function step(page: Page, button: string, dialogTitle: RegExp, confirm = button) {
  await quoteActions(page).getByRole("button", { name: button }).click();
  const dialog = page.getByRole("dialog", { name: dialogTitle });
  await dialog.getByRole("button", { name: confirm }).click();
} // prettier-ignore

test("a discounted quote is approved, sent, accepted by the customer and becomes an order", async ({
  browser,
}) => {
  test.setTimeout(180_000);
  const sku = uniqueName("E2E-");
  const productName = `E2E widget ${sku}`;
  const title = uniqueName("E2E quote ");

  // 1. The manager adds a product (validation first) and prices it in the default book.
  const manager = await signedIn(browser, USERS.manager, "/products/new");
  await manager.getByRole("button", { name: "Create product" }).click();
  await expect(manager.getByText("Enter a product code (SKU).")).toBeVisible();
  await manager.getByLabel("Product code (SKU)").fill(sku);
  await manager.getByLabel("Name").fill(productName);
  await manager.getByLabel("Tax rate %").fill("19");
  await manager.getByRole("button", { name: "Create product" }).click();
  await expect(manager.getByRole("status")).toContainText("The product was created.");

  await manager.goto("/products");
  await manager.getByRole("link", { name: "Standard EUR" }).click();
  await manager.getByRole("button", { name: "Add price" }).click();
  const priceDialog = manager.getByRole("dialog", { name: "Add a product to this price book" });
  await priceDialog.getByLabel("Product").selectOption({ label: `${sku} – ${productName}` });
  await priceDialog.getByLabel(/Unit price/).fill("100");
  await priceDialog.getByRole("button", { name: "Save price" }).click();
  await expect(manager.getByRole("status")).toHaveText("The price was saved.");
  await expect(manager.getByRole("row", { name: new RegExp(sku) })).toContainText("€100.00");

  // 2. The agent quotes it with 15 % off: the preview flags the approval, the server prices it.
  const agent = await signedIn(browser, USERS.agent1, "/quotes/new");
  await agent.getByLabel("Title").fill(title);
  await chooseAccount(agent, "Account", "Example Customer One Ltd");
  await agent.getByRole("button", { name: "Add line" }).click();
  await agent.getByLabel("Line 1 product").selectOption({ label: `${sku} – ${productName}` });
  await agent.getByLabel("Line 1 quantity").fill("2");
  await agent.getByLabel("Line 1 discount").fill("15");
  const preview = agent.getByLabel("Totals preview");
  await expect(preview).toContainText("€202.30");
  await expect(preview).toContainText("needs a manager's approval");
  await agent.getByLabel("Internal note").fill("E2E internal: never printed");
  await agent.getByRole("button", { name: "Create quote" }).click();
  await expect(agent.getByRole("status")).toHaveText("The quote was created.");
  const quoteId = agent.url().split("/quotes/")[1].split("?")[0];
  await expect(agent.getByText("€202.30").first()).toBeVisible(); // server total

  // The customer can't see a draft.
  const customer = await signedIn(browser, USERS.customer, `/portal/quotes/${quoteId}`);
  await expect(customer.getByRole("heading", { name: "Page not found" })).toBeVisible();

  await step(agent, "Submit", /Submit this quote/);
  await expect(agent.getByRole("status")).toHaveText("The quote was submitted.");
  await expect(agent.getByText("Waiting for approval").first()).toBeVisible();
  // Agents can't approve, and can't send before approval.
  await expect(quoteActions(agent).getByRole("button", { name: "Approve" })).toHaveCount(0);
  await expect(quoteActions(agent).getByRole("button", { name: "Mark as sent" })).toHaveCount(0);

  // 3. The manager approves (someone other than the owner: four-eyes rule).
  await manager.goto(`/quotes/${quoteId}`);
  await step(manager, "Approve", /Approve this quote/);
  await expect(manager.getByRole("status")).toHaveText("The quote was approved.");

  // 4. The agent sends it; now the customer sees and accepts it.
  await agent.reload();
  await step(agent, "Mark as sent", /Mark as sent/);
  await expect(agent.getByRole("status")).toContainText("The quote is marked as sent.");

  await customer.goto("/portal/quotes");
  await customer.getByRole("link", { name: new RegExp(title) }).click();
  await expect(customer.getByText("€202.30").first()).toBeVisible();
  await expect(customer.getByText("E2E internal")).toHaveCount(0); // internal note stays internal
  await customer.getByRole("button", { name: "Accept quote" }).click();
  await customer
    .getByRole("dialog", { name: "Accept this quote?" })
    .getByRole("button", { name: "Accept quote" })
    .click();
  await expect(customer.getByRole("status")).toContainText("We received your acceptance");

  // The customer downloads the stored PDF (ADR 0005); the agent gets the very same file.
  const customerPdf = await downloadPdf(customer);
  expect(customerPdf.name).toMatch(/^QT-\d{4,}\.pdf$/);
  expect(customerPdf.bytes.subarray(0, 5).toString()).toBe("%PDF-");
  await agent.goto(`/quotes/${quoteId}`);
  const agentPdf = await downloadPdf(agent);
  expect(agentPdf.bytes.equals(customerPdf.bytes)).toBe(true);
  // Another customer can't fetch it, even with the address.
  const other = await signedIn(browser, USERS.customer2, "/portal");
  const refused = await other.request.get(`/portal/quotes/${quoteId}/pdf`, { maxRedirects: 0 });
  expect(refused.status()).toBe(307); // back to the quote page with "file=missing"
  expect(refused.headers()["location"]).toContain("file=missing");

  // 5. Printable version (staff): released quotes only, no internal note.
  await agent.goto(`/print/quotes/${quoteId}`);
  await expect(agent.getByRole("button", { name: "Print / Save as PDF" })).toBeVisible();
  await expect(agent.getByText(title)).toBeVisible();
  await expect(agent.getByText("E2E internal")).toHaveCount(0);

  // 6. The agent turns the accepted quote into a draft order with the same totals.
  await agent.goto(`/quotes/${quoteId}`);
  await expect(agent.getByText("Accepted").first()).toBeVisible();
  await quoteActions(agent).getByRole("button", { name: "Create order" }).click();
  const orderDialog = agent.getByRole("dialog", { name: "Create an order from this quote?" });
  await orderDialog.getByLabel(/Customer reference/).fill("PO-E2E-QUOTE");
  await orderDialog.getByRole("button", { name: "Create order" }).click();
  await expect(agent.getByRole("status")).toHaveText("A draft order was created from this quote.");
  await expect(quoteActions(agent).getByRole("button", { name: "Create order" })).toHaveCount(0);

  await agent.getByRole("link", { name: "Open the order" }).click();
  await expect(agent.getByRole("heading", { level: 1 })).toHaveText(/^SO-\d{4,}$/);
  await expect(agent.getByText("€202.30").first()).toBeVisible();
  await expect(agent.getByRole("link", { name: /^QT-\d{4,}/ })).toBeVisible(); // "From quote"
}); // prettier-ignore

test("agents can read the catalogue but not change it", async ({ page }) => {
  await login(page, USERS.agent1, "/products");
  await expect(page.getByRole("heading", { name: "Products", level: 1 })).toBeVisible();
  await expect(page.getByRole("link", { name: "New product" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "New price book" })).toHaveCount(0);
  await page.goto("/products/new");
  await expect(page.getByText("You don't have access to this page")).toBeVisible();
}); // prettier-ignore

/** Runs the background worker once (it sends queued e-mails and stores PDFs), like the
 * "python -m app.worker" window would. */
function runWorkerOnce() {
  execFileSync(path.join("..", "backend", ".venv", "Scripts", "python.exe"), ["-m", "app.worker", "--once"], {
    cwd: path.join("..", "backend"),
    timeout: 60_000,
    stdio: "ignore",
  });
}

test("an approved quote is e-mailed to its contact with the PDF attached", async ({ browser }) => {
  test.setTimeout(150_000);
  const lastName = uniqueName("E2eMail");
  const address = `${lastName.toLowerCase()}@example.test`; // fictional; Mailpit catches it
  const title = uniqueName("E2E mailed quote ");

  // A contact with an e-mail address at the agent's customer.
  const agent = await signedIn(browser, USERS.agent1, "/contacts/new");
  await agent.getByLabel(/^Account/).selectOption({ label: "Example Customer One Ltd" }); // the contact form still has a plain dropdown
  await agent.getByLabel(/First name/).fill("Ada");
  await agent.getByLabel(/Last name/).fill(lastName);
  await agent.getByLabel(/^E-mail/).fill(address);
  await agent.getByRole("button", { name: "Create contact" }).click();
  await expect(agent.getByText("The contact was created.")).toBeVisible();

  // A quote for that contact, without a big discount: approved straight away.
  await agent.goto("/quotes/new");
  await agent.getByLabel("Title").fill(title);
  await chooseAccount(agent, "Account", "Example Customer One Ltd");
  await agent.getByLabel(/For \(contact\)/).selectOption({ label: `Ada ${lastName}` });
  await agent.getByRole("button", { name: "Add line" }).click();
  await agent.getByLabel("Line 1 product").selectOption({ label: "WID-100 – Demo widget" });
  await agent.getByLabel("Line 1 quantity").fill("2");
  await agent.getByRole("button", { name: "Create quote" }).click();
  await expect(agent.getByRole("status")).toHaveText("The quote was created.");
  await step(agent, "Submit", /Submit this quote/);
  await expect(agent.getByText("Approved").first()).toBeVisible();

  // Send by e-mail: the dialog names the recipient; the API picks it, not the browser.
  await quoteActions(agent).getByRole("button", { name: "Send by e-mail" }).click();
  const dialog = agent.getByRole("dialog", { name: "Send this quote by e-mail?" });
  await expect(dialog).toContainText(address);
  await dialog.getByLabel(/Personal message/).fill("As discussed on the phone.");
  await dialog.getByRole("button", { name: "Send e-mail" }).click();
  await expect(agent.getByRole("status")).toContainText("The e-mail is on its way");
  await expect(agent.getByText("On its way…")).toBeVisible();

  runWorkerOnce();
  const mail = await latestMessageTo(address);
  expect(mail.Subject).toMatch(/^Quote QT-\d{4,}: /);
  expect(mail.Subject.endsWith(title)).toBe(true);
  expect(mail.Text).toContain(`Hello Ada ${lastName},`);
  expect(mail.Text).toContain("As discussed on the phone.");
  expect(mail.Text).toContain("/portal/quotes/");
  expect(mail.Attachments.map((a) => [a.FileName.replace(/\d+/, "N"), a.ContentType])).toEqual([
    ["QT-N.pdf", "application/pdf"],
  ]);

  await agent.reload();
  await expect(agent.getByText("Sent to the contact")).toBeVisible();
  await expect(agent.getByText(`E-mail sent to Ada ${lastName}`)).toBeVisible();
}); // prettier-ignore

async function setApprovalLimit(page: Page, value: string) {
  await page.goto("/quotes/settings");
  await page.getByLabel(/Approval needed above/).fill(value);
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByRole("status")).toContainText("The approval limit was saved.");
}

test("an admin changes the discount that needs approval", async ({ browser }) => {
  test.setTimeout(120_000);
  const admin = await signedIn(browser, USERS.admin, "/quotes");
  await admin.getByRole("link", { name: "Settings" }).click();
  await expect(admin.getByText(/above 10 %/)).toBeVisible();
  try {
    await setApprovalLimit(admin, "20");
    await expect(admin.getByText(/above 20 %/)).toBeVisible();

    // Agents see the rule but can't change it.
    const agent = await signedIn(browser, USERS.agent1, "/quotes/settings");
    await expect(agent.getByText(/above 20 %/)).toBeVisible();
    await expect(agent.getByText("Only administrators can change this.")).toBeVisible();
    await expect(agent.getByRole("button", { name: "Save" })).toHaveCount(0);

    // A 15 % discount no longer needs approval - in the preview and on the server.
    await agent.goto("/quotes/new");
    await agent.getByLabel("Title").fill(uniqueName("E2E limit quote "));
    await chooseAccount(agent, "Account", "Example Customer One Ltd");
    await agent.getByRole("button", { name: "Add line" }).click();
    await agent.getByLabel("Line 1 product").selectOption({ label: "WID-100 – Demo widget" });
    await agent.getByLabel("Line 1 discount").fill("15");
    await expect(agent.getByLabel("Totals preview")).not.toContainText("needs a manager's approval");
    await agent.getByLabel("Line 1 discount").fill("25");
    await expect(agent.getByLabel("Totals preview")).toContainText("above 20 %");
    await agent.getByLabel("Line 1 discount").fill("15");
    await agent.getByRole("button", { name: "Create quote" }).click();
    await expect(agent.getByRole("status")).toHaveText("The quote was created.");
    await step(agent, "Submit", /Submit this quote/);
    await expect(agent.getByText("Approved").first()).toBeVisible();

    // Bad values are refused before anything is saved.
    await admin.goto("/quotes/settings");
    await admin.getByLabel(/Approval needed above/).fill("150");
    await admin.getByRole("button", { name: "Save" }).click();
    await expect(admin.getByText("Enter a percentage from 0 to 100")).toBeVisible();
  } finally {
    await setApprovalLimit(admin, "10"); // leave the shared demo data as it was
  }
}); // prettier-ignore
