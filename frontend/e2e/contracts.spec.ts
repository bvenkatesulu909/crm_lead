import { expect, test, type Browser, type Page } from "@playwright/test";

import { USERS, login, requireCredentials, uniqueName } from "./helpers";

/**
 * Contracts and renewals (docs/contracts.md, step C4), end to end.
 * The agent records a contract on their own account (a draft); the manager activates it, renews
 * it and activates the renewal (the old contract becomes "renewed"); another contract is
 * terminated with a reason. Other people see only what they may. Creates clearly fictional
 * "E2E…" records. alpha.agent1 owns "Example Customer One Ltd", alpha.agent2 owns Two.
 */
test.beforeEach(() => requireCredentials());

async function signedIn(browser: Browser, user: string, target = "/") {
  const page = await (await browser.newContext()).newPage();
  await login(page, user, target);
  return page;
}

const actions = (page: Page) =>
  page.getByRole("group", { name: "Contract actions" });

const isoDay = (offset: number) =>
  new Date(Date.now() + offset * 86_400_000).toISOString().slice(0, 10);

/** The agent creates a draft on the account page and returns its address. */
async function createDraft(agent: Page, title: string, endInDays = 100) {
  await agent.goto("/accounts?q=example+customer+one");
  await agent.getByRole("link", { name: "Example Customer One Ltd" }).click();
  await agent.getByRole("link", { name: "New contract" }).click();
  // The account is already chosen (we came from its page).
  await expect(agent.getByRole("combobox", { name: "Account" })).toHaveValue(
    "Example Customer One Ltd",
  );
  await agent.getByLabel("Title").fill(title);
  await agent.getByLabel("Start date").fill(isoDay(0));
  await agent.getByLabel("End date").fill(isoDay(endInDays));
  await agent.getByLabel("Total value").fill("12000.50");
  await agent.getByRole("button", { name: "Create draft" }).click();
  await expect(agent.getByRole("status")).toContainText(
    "The contract was created as a draft.",
  );
  return new URL(agent.url()).pathname;
}

test("a draft is activated, renewed and the renewal replaces it", async ({
  browser,
}) => {
  test.setTimeout(180_000);
  const title = uniqueName("E2E contract ");

  // 1. The agent records the contract. Validation first, then the real thing.
  const agent = await signedIn(browser, USERS.agent1, "/contracts/new");
  await agent.getByRole("button", { name: "Create draft" }).click();
  await expect(
    agent.getByText("Give the contract a title.").first(),
  ).toBeVisible();
  await expect(
    agent.getByText("Choose the customer account.").first(),
  ).toBeVisible();
  await agent.getByLabel("Title").fill(title);
  await agent.getByLabel("End date").fill(isoDay(10));
  await agent.getByLabel("Start date").fill(isoDay(20));
  await agent.getByRole("button", { name: "Create draft" }).click();
  await expect(
    agent.getByText("The end date cannot be before the start date.").first(),
  ).toBeVisible();

  const path = await createDraft(agent, title);
  await expect(agent.getByRole("heading", { name: title })).toBeVisible();
  await expect(agent.getByText("Draft", { exact: true })).toBeVisible();
  // Activating is a manager's decision: the agent has no such button.
  await expect(
    actions(agent).getByRole("button", { name: "Activate" }),
  ).toHaveCount(0);
  await expect(
    actions(agent).getByRole("link", { name: "Edit" }),
  ).toBeVisible();

  // 2. The manager activates it.
  const manager = await signedIn(browser, USERS.manager, path);
  await actions(manager).getByRole("button", { name: "Activate" }).click();
  await manager
    .getByRole("dialog", { name: "Activate this contract?" })
    .getByRole("button", { name: "Activate" })
    .click();
  await expect(manager.getByRole("status")).toContainText(
    "The contract is active.",
  );
  await expect(manager.getByText("Active", { exact: true })).toBeVisible();
  await expect(manager.getByText(/Ends in \d+ days/)).toBeVisible();
  await expect(manager.getByText("Status: Active")).toBeVisible(); // in the history
  // Dates and value are now fixed: the edit form says so.
  await actions(manager).getByRole("link", { name: "Edit" }).click();
  await expect(manager.getByText(/renew the contract/)).toBeVisible();
  await expect(manager.getByLabel("Total value")).toHaveCount(0);
  await manager.goto(path);

  // 3. The manager renews it: a linked draft appears; the old contract points to it.
  await actions(manager).getByRole("button", { name: "Renew" }).click();
  await manager
    .getByRole("dialog", { name: "Renew this contract?" })
    .getByRole("button", { name: "Create renewal" })
    .click();
  await expect(manager.getByRole("status")).toContainText(
    "The renewal was created as a draft.",
  );
  await expect(manager.getByText("Draft", { exact: true })).toBeVisible();
  await expect(
    manager.getByRole("link", { name: "The previous contract" }),
  ).toBeVisible();
  const renewalPath = new URL(manager.url()).pathname;

  await manager.goto(path);
  await expect(
    manager.getByRole("link", { name: "The renewal" }),
  ).toBeVisible();
  await expect(
    actions(manager).getByRole("button", { name: "Renew" }),
  ).toHaveCount(0); // one at a time

  // 4. Activating the renewal completes it: the old contract becomes "Renewed".
  await manager.goto(renewalPath);
  await actions(manager).getByRole("button", { name: "Activate" }).click();
  await manager
    .getByRole("dialog", { name: "Activate this contract?" })
    .getByRole("button", { name: "Activate" })
    .click();
  await expect(manager.getByRole("status")).toContainText(
    "The contract is active.",
  );
  await manager.goto(path);
  await expect(manager.getByText("Renewed", { exact: true })).toBeVisible();
});

test("terminating needs a reason and ends the contract for good", async ({
  browser,
}) => {
  test.setTimeout(150_000);
  const title = uniqueName("E2E ended ");
  const agent = await signedIn(browser, USERS.agent1);
  const path = await createDraft(agent, title);

  const manager = await signedIn(browser, USERS.manager, path);
  await actions(manager).getByRole("button", { name: "Activate" }).click();
  await manager
    .getByRole("dialog", { name: "Activate this contract?" })
    .getByRole("button", { name: "Activate" })
    .click();
  await expect(manager.getByRole("status")).toContainText(
    "The contract is active.",
  );

  await actions(manager).getByRole("button", { name: "Terminate" }).click();
  const dialog = manager.getByRole("dialog", {
    name: "End this contract early?",
  });
  await dialog.getByRole("button", { name: "Terminate" }).click();
  await expect(dialog.getByText("Please give a reason.")).toBeVisible();
  await dialog
    .getByLabel("Reason")
    .fill("The customer moved to another provider");
  await dialog.getByRole("button", { name: "Terminate" }).click();
  await expect(manager.getByRole("status")).toContainText(
    "The contract was terminated.",
  );
  await expect(manager.getByText("Terminated", { exact: true })).toBeVisible();
  await expect(
    manager.getByText("The customer moved to another provider").first(),
  ).toBeVisible();
  // Final: no edit, no renewal, no second termination.
  for (const button of ["Edit", "Renew", "Terminate", "Activate"])
    await expect(
      actions(manager).getByText(button, { exact: true }),
    ).toHaveCount(0);
});

test("the list filters, and people only see what they may", async ({
  browser,
}) => {
  test.setTimeout(150_000);
  const title = uniqueName("E2E visible ");
  const agent = await signedIn(browser, USERS.agent1);
  const path = await createDraft(agent, title);

  // Search and status filter on the list (the manager sees every contract).
  const manager = await signedIn(browser, USERS.manager, "/contracts");
  await expect(
    manager.getByRole("heading", { name: "Contracts" }),
  ).toBeVisible();
  await manager.getByLabel("Search").fill(title);
  await manager.getByLabel("Status").selectOption("draft");
  await manager.getByRole("button", { name: "Apply" }).click();
  await expect(
    manager.getByRole("link", { name: new RegExp(title) }),
  ).toBeVisible();
  await manager.getByLabel("Status").selectOption("terminated");
  await manager.getByRole("button", { name: "Apply" }).click();
  await expect(manager.getByText("No contracts match")).toBeVisible();

  // Another agent has no access to this account's contract: the page does not exist for them.
  const other = await signedIn(browser, USERS.agent2, "/contracts");
  await other.getByLabel("Search").fill(title);
  await other.getByRole("button", { name: "Apply" }).click();
  await expect(other.getByText("No contracts match")).toBeVisible();
  await other.goto(path);
  await expect(
    other.getByRole("heading", { name: "Page not found" }),
  ).toBeVisible();

  // Support has no contracts at all: no menu entry, and the page says so.
  const support = await signedIn(browser, USERS.support);
  await expect(
    support
      .getByRole("navigation", { name: "Main" })
      .getByRole("link", { name: "Contracts" }),
  ).toHaveCount(0);
  await support.goto("/contracts");
  await expect(
    support.getByText("You don't have access to this page"),
  ).toBeVisible();
});
