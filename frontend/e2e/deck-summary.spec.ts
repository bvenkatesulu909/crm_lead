import { expect, test, type Browser, type Page } from "@playwright/test";

import {
  USERS,
  chooseAccount,
  login,
  requireCredentials,
  uniqueName,
} from "./helpers";

/**
 * The "Why this proposal" slide (ADR 0032 Amendment A, PD7), end to end with the SCRIPTED model: an
 * administrator switches the deck writer on (it starts off), a sales agent drafts the slide on an
 * approved quote, the draft only WAITS in the approval queue (the asker cannot approve it and the
 * quote card shows no text yet), a manager approves it, and only then does the quote card show the
 * text. Switched off again at the end. Creates clearly fictional "E2E" records.
 *
 * Needs the scripted model: CRM_AI_PROVIDER=fake for the API and E2E_FAKE_ASSISTANT=1 for this run
 * (the same switch as the approvals and lead agent journeys). Without it the spec is skipped.
 */
test.beforeEach(() => {
  requireCredentials();
  test.skip(
    !process.env.E2E_FAKE_ASSISTANT,
    "E2E_FAKE_ASSISTANT is not set (scripted model switched off)",
  );
});

async function signedIn(
  browser: Browser,
  user: string,
  target = "/",
): Promise<Page> {
  const page = await (await browser.newContext()).newPage();
  await login(page, user, target);
  return page;
}

async function switchDeckWriter(page: Page, on: boolean) {
  await page.goto("/automation/agents");
  const box = page.getByRole("article", { name: "Deck writer" });
  const toggle = box.getByLabel("Switched on");
  if ((await toggle.isChecked()) !== on) {
    if (on) await toggle.check();
    else await toggle.uncheck();
    await box.getByRole("button", { name: "Save settings" }).click();
    await expect(page.getByText(/were saved/)).toBeVisible();
  }
}

test("the deck writer drafts, a manager approves, and only then the card shows the text", async ({
  browser,
}) => {
  test.setTimeout(600_000);
  const sku = uniqueName("E2E-");
  const productName = `E2E summary widget ${sku}`;
  const title = uniqueName("E2E summary quote ");

  // 1. The manager adds a product and its price (as the deck journey does).
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

  // 2. An administrator switches the deck writer on; the agent creates and submits a quote.
  const admin = await signedIn(browser, USERS.admin);
  try {
    await switchDeckWriter(admin, true);
    const agent = await signedIn(browser, USERS.agent1, "/quotes/new");
    await agent.getByLabel("Title").fill(title);
    await chooseAccount(agent, "Account", "Example Customer One Ltd");
    await agent.getByRole("button", { name: "Add line" }).click();
    await agent
      .getByLabel("Line 1 product")
      .selectOption({ label: `${sku} – ${productName}` });
    await agent.getByLabel("Line 1 quantity").fill("2");
    await agent.getByRole("button", { name: "Create quote" }).click();
    await expect(agent.getByRole("status")).toHaveText(
      "The quote was created.",
    );
    const quoteId = agent.url().split("/quotes/")[1].split("?")[0];
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

    // 3. The agent drafts the slide: it opens the proposal, which only WAITS.
    const block = agent.getByRole("region", { name: "Why this proposal" });
    await expect(block.getByTestId("deck-summary")).toHaveText(
      "No summary slide yet.",
    );
    await block
      .getByRole("button", { name: "Draft with the deck writer" })
      .click();
    await expect(agent).toHaveURL(/\/approvals\/[0-9a-f-]{36}/);
    await expect(agent.getByText("the deck writer").first()).toBeVisible();
    await expect(
      agent.getByRole("button", { name: "Approve", exact: true }),
    ).toHaveCount(0); // the asker cannot approve their own proposal
    await agent.goto(`/quotes/${quoteId}`);
    await expect(
      agent
        .getByRole("region", { name: "Why this proposal" })
        .getByTestId("deck-summary"),
    ).toHaveText("No summary slide yet."); // nothing is drawn or shown before approval

    // 4. A manager approves it in the queue; only now does the quote card show the text.
    await manager.goto("/approvals");
    const waiting = manager.getByRole("article").filter({ hasText: title });
    await expect(waiting).toContainText("deck writer");
    await waiting.getByRole("button", { name: "Approve", exact: true }).click();
    await waiting.getByRole("button", { name: "Approve and run" }).click();
    await expect(manager.getByText("The proposal was approved.")).toBeVisible();
    await agent.goto(`/quotes/${quoteId}`);
    await expect(
      agent
        .getByRole("region", { name: "Why this proposal" })
        .getByTestId("deck-summary"),
    ).toContainText("This proposal was prepared for");

    // 5. Switched off again, the button explains why and nothing is drafted.
    await switchDeckWriter(admin, false);
    await agent.goto(`/quotes/${quoteId}`);
    await agent
      .getByRole("region", { name: "Why this proposal" })
      .getByRole("button", { name: "Draft a new one" })
      .click();
    await expect(
      agent.getByText(/The deck writer is switched off/),
    ).toBeVisible();
  } finally {
    await switchDeckWriter(admin, false); // leave it as it starts
  }
});

test("a support agent sees no summary block", async ({ browser }) => {
  const support = await signedIn(browser, USERS.support, "/quotes");
  await expect(
    support.getByRole("region", { name: "Why this proposal" }),
  ).toHaveCount(0);
});
