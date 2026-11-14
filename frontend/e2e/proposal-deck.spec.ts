import { execFileSync } from "node:child_process";
import { readFile } from "node:fs/promises";
import path from "node:path";

import { expect, test, type Browser, type Page } from "@playwright/test";

import {
  USERS,
  chooseAccount,
  login,
  requireCredentials,
  uniqueName,
} from "./helpers";

/**
 * Branded proposal decks (ADR 0032, PD4), end to end: a manager prices a product, an agent quotes it,
 * the Proposal deck card says a deck is not available while the quote is a draft, the agent submits it
 * (approved at once, no discount), asks for a deck, the card shows the work in progress and updates by
 * itself when the worker has run, the deck downloads as a PDF. An administrator changes the branding
 * and a new deck is made; the customer sees the button only once the quote was sent to them and gets
 * the same newest file; another customer is refused. Creates clearly fictional "E2E" records and puts
 * the branding's about text back. Like the other journeys that run the worker themselves it expects NO
 * standing worker.
 */
test.beforeEach(() => requireCredentials());

function runWorkerOnce() {
  execFileSync(
    path.join("..", "backend", ".venv", "Scripts", "python.exe"),
    ["-m", "app.worker", "--once"],
    { cwd: path.join("..", "backend"), timeout: 90_000, stdio: "ignore" },
  );
}

async function signedIn(
  browser: Browser,
  user: string,
  target = "/",
): Promise<Page> {
  const page = await (await browser.newContext()).newPage();
  await login(page, user, target);
  return page;
}

async function downloadDeck(page: Page, name: string) {
  const [download] = await Promise.all([
    page.waitForEvent("download"),
    page.getByRole("link", { name }).click(),
  ]);
  return {
    name: download.suggestedFilename(),
    bytes: await readFile(await download.path()),
  };
}

test("a proposal deck is made for a quote, downloaded and shared with the customer", async ({
  browser,
}) => {
  test.setTimeout(600_000);
  const sku = uniqueName("E2E-");
  const productName = `E2E deck widget ${sku}`;
  const title = uniqueName("E2E deck quote ");

  // 1. The manager adds a product and its price.
  const manager = await signedIn(browser, USERS.manager, "/products/new");
  await manager.getByLabel("Product code (SKU)").fill(sku);
  await manager.getByLabel("Name").fill(productName);
  await manager.getByLabel("Tax rate %").fill("19");
  await manager.getByRole("button", { name: "Create product" }).click();
  await expect(manager.getByRole("status")).toContainText(
    "The product was created.",
  );
  await manager.goto("/products");
  await manager.getByRole("link", { name: "Standard EUR" }).click();
  await manager.getByRole("button", { name: "Add price" }).click();
  const priceDialog = manager.getByRole("dialog", {
    name: "Add a product to this price book",
  });
  await priceDialog
    .getByLabel("Product")
    .selectOption({ label: `${sku} – ${productName}` });
  await priceDialog.getByLabel(/Unit price/).fill("100");
  await priceDialog.getByRole("button", { name: "Save price" }).click();
  await expect(manager.getByRole("status")).toHaveText("The price was saved.");

  // 2. The agent creates a quote without discount. While it is a draft there is no deck.
  const agent = await signedIn(browser, USERS.agent1, "/quotes/new");
  await agent.getByLabel("Title").fill(title);
  await chooseAccount(agent, "Account", "Example Customer One Ltd");
  await agent.getByRole("button", { name: "Add line" }).click();
  await agent
    .getByLabel("Line 1 product")
    .selectOption({ label: `${sku} – ${productName}` });
  await agent.getByLabel("Line 1 quantity").fill("2");
  await agent.getByRole("button", { name: "Create quote" }).click();
  await expect(agent.getByRole("status")).toHaveText("The quote was created.");
  const quoteId = agent.url().split("/quotes/")[1].split("?")[0];
  const card = agent.getByRole("region", { name: "Proposal deck" });
  await expect(card.getByTestId("deck-state")).toContainText(
    /once the quote is approved/,
  );
  await expect(card.getByRole("button")).toHaveCount(0);

  // 3. Submitted without a discount the quote is approved at once: now a deck can be asked for.
  await agent
    .getByRole("group", { name: "Quote actions" })
    .getByRole("button", { name: "Submit" })
    .click();
  await agent
    .getByRole("dialog", { name: /Submit this quote/ })
    .getByRole("button", { name: "Submit" })
    .click();
  await expect(agent.getByRole("status")).toHaveText(
    "The quote was submitted.",
  );
  await expect(card.getByTestId("deck-state")).toHaveText("No deck yet.");
  await card.getByRole("button", { name: "Create proposal deck" }).click();
  await expect(agent.getByRole("status").first()).toContainText(/being made/);
  await expect(card.getByRole("button", { name: "Making…" })).toBeDisabled();

  // 4. The worker draws it; the card notices on its own and the deck downloads as a PDF.
  runWorkerOnce();
  await expect(card.getByTestId("deck-state")).toHaveText(
    "The deck is ready.",
    { timeout: 30_000 },
  );
  await expect(card).toContainText(/-proposal\.pdf/);
  const first = await downloadDeck(agent, "Download deck");
  expect(first.name).toMatch(/^QT-\d{4,}-proposal\.pdf$/);
  expect(first.bytes.subarray(0, 5).toString()).toBe("%PDF-");
  expect(first.bytes.length).toBeGreaterThan(5000);

  // 5. The customer sees nothing while the quote is not yet sent to them.
  const customer = await signedIn(
    browser,
    USERS.customer,
    `/portal/quotes/${quoteId}`,
  );
  await expect(
    customer.getByRole("heading", { name: "Page not found" }),
  ).toBeVisible();

  // 6. The branding changes; a new deck is made and replaces the old one for downloads.
  const admin = await signedIn(browser, USERS.admin, "/branding");
  const originalAbout = await admin.getByLabel(/About us/).inputValue();
  await admin.getByLabel(/About us/).fill(`E2E branding text ${Date.now()}`);
  await admin.getByRole("button", { name: "Save branding" }).click();
  await expect(admin.getByRole("status")).toContainText(
    "The branding was saved.",
  );
  try {
    await agent.reload();
    await card.getByRole("button", { name: "Make a new deck" }).click();
    runWorkerOnce();
    await expect(card.getByRole("link", { name: "Download deck" })).toBeVisible(
      { timeout: 30_000 },
    );
    await expect(card.getByTestId("deck-state")).toHaveText(
      "The deck is ready.",
      { timeout: 30_000 },
    );
    const second = await downloadDeck(agent, "Download deck");
    expect(second.bytes.subarray(0, 5).toString()).toBe("%PDF-");
    expect(second.bytes.equals(first.bytes)).toBe(false);

    // 7. The agent marks the quote as sent: the customer now sees the button and gets the newest deck.
    await agent
      .getByRole("group", { name: "Quote actions" })
      .getByRole("button", { name: "Mark as sent" })
      .click();
    await agent
      .getByRole("dialog", { name: /Mark as sent/ })
      .getByRole("button", { name: "Mark as sent" })
      .click();
    await expect(agent.getByRole("status").first()).toContainText(
      "The quote is marked as sent.",
    );
    await customer.goto(`/portal/quotes/${quoteId}`);
    const forCustomer = await downloadDeck(customer, "Download proposal deck");
    expect(forCustomer.bytes.equals(second.bytes)).toBe(true);

    // Another customer cannot fetch it, even with the address.
    const other = await signedIn(browser, USERS.customer2, "/portal");
    const refused = await other.request.get(`/portal/quotes/${quoteId}/deck`, {
      maxRedirects: 0,
    });
    expect(refused.status()).toBe(307);
    expect(refused.headers()["location"]).toContain("file=missing");
  } finally {
    await admin.goto("/branding");
    await admin.getByLabel(/About us/).fill(originalAbout);
    await admin.getByRole("button", { name: "Save branding" }).click();
    await expect(admin.getByRole("status")).toContainText(
      "The branding was saved.",
    );
  }
});
