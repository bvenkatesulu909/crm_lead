import { expect, test, type Browser } from "@playwright/test";

import { login, requireCredentials, uniqueName } from "./helpers";

/**
 * The deal risk forecast (ADR 0037, DR4), end to end. No AI is involved: the risk is worked out
 * by fixed rules from the deal's own records.
 *
 * A sales agent creates a deal with no next step and a close date in the past. A manager opens it,
 * works out the forecast and sees the level, the reasons in plain words and the note that it is an
 * estimate; the pipeline shows the level as a badge and can filter by it; the dashboard counts the
 * deals at high risk. The sales agent who owns the deal sees no forecast card (managers and
 * administrators only, ADR 0037 question 6).
 *
 * Creates clearly fictional "E2eDealRisk…" records.
 */
test.beforeEach(() => {
  requireCredentials();
});

async function signedIn(browser: Browser, user: string, target = "/") {
  const page = await (await browser.newContext()).newPage();
  await login(page, user, target);
  return page;
}

test("a manager works out a deal's risk and sees why; the owner sees no forecast", async ({
  browser,
}) => {
  test.setTimeout(240_000);
  const name = uniqueName("E2eDealRisk");

  // A sales agent's account and a deal whose close date has already passed, with nothing planned.
  const agent = await signedIn(browser, "alpha.agent1", "/accounts/new");
  await agent.getByLabel("Name").fill(`${name} account`);
  await agent.getByRole("button", { name: "Create account" }).click();
  await expect(agent.getByText("The account was created.")).toBeVisible({
    timeout: 20_000,
  });
  const accountId = agent.url().split("/accounts/")[1].split("?")[0];
  await agent.goto(`/opportunities/new?account=${accountId}`);
  await agent.getByLabel("Name").fill(name);
  await agent.getByLabel(/Expected close/).fill("2026-01-15");
  await agent.getByRole("button", { name: "Create opportunity" }).click();
  await expect(agent.getByText("The opportunity was created.")).toBeVisible({
    timeout: 20_000,
  });
  const deal = agent.url().split("/opportunities/")[1].split("?")[0];

  // The owner is a sales agent: no forecast card on their own deal.
  await agent.goto(`/opportunities/${deal}`);
  await expect(
    agent.getByRole("heading", { name: "Deal risk forecast" }),
  ).toHaveCount(0);

  // A manager opens the deal: no forecast yet, then works it out.
  const manager = await signedIn(
    browser,
    "alpha.manager",
    `/opportunities/${deal}`,
  );
  const card = manager.locator("#deal-risk");
  await expect(card.getByText(/No forecast has been worked out/)).toBeVisible();
  await card.getByRole("button", { name: "Work out the forecast" }).click();
  await expect(
    manager.getByText("The deal risk forecast was updated."),
  ).toBeVisible({ timeout: 20_000 });

  // The reasons are written out, the level is a word and the estimate note is there.
  await expect(card.getByText(/expected close date passed/)).toBeVisible();
  await expect(card.getByText("The deal has no primary contact")).toBeVisible();
  await expect(card.getByTestId("risk-badge")).toHaveText(
    /^(Low|Medium|High) risk$/,
  );
  await expect(
    card.getByText(/not a promise and not a probability/),
  ).toBeVisible();
  await expect(
    card.getByRole("button", { name: "Update forecast" }),
  ).toBeVisible();
  const level = (await card.getByTestId("risk-badge").innerText())
    .split(" ")[0]
    .toLowerCase();

  // The pipeline shows the level on the deal's card and can filter by it.
  await manager.goto(`/opportunities?risk=${level}`);
  const dealCard = manager.getByTestId("deal-card").filter({ hasText: name });
  await expect(dealCard).toHaveCount(1);
  await expect(dealCard.getByTestId("risk-badge")).toBeVisible();
  const other = level === "high" ? "low" : "high";
  await manager.goto(`/opportunities?risk=${other}`);
  await expect(
    manager.getByTestId("deal-card").filter({ hasText: name }),
  ).toHaveCount(0);

  // The dashboard has the forecast tiles for a manager.
  await manager.goto("/");
  await expect(
    manager.getByRole("region", { name: "Deal risk forecast" }),
  ).toBeVisible();
  await expect(manager.getByTestId("risk-high-count")).toBeVisible();

  // The sales agent's pipeline has no risk filter and no badges.
  await agent.goto("/opportunities");
  await expect(agent.getByLabel("Risk forecast")).toHaveCount(0);
  await expect(agent.getByTestId("risk-badge")).toHaveCount(0);
});
