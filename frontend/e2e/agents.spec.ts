import { expect, test, type Page } from "@playwright/test";

import { USERS, login, requireCredentials } from "./helpers";

/**
 * AI agents page (ADR 0016, BP-14), end to end: a tenant admin switches an AI agent off, caps
 * its monthly tokens and takes a tool away; a sales manager can read but not change; an agent
 * has no page at all. Touches only two agents nobody else's journey depends on while it runs
 * (knowledge answers, website chat) and puts them back in a `finally`.
 */
test.beforeEach(() => {
  requireCredentials();
});

const card = (page: Page, title: string) =>
  page.getByRole("article", { name: title });

async function restore(page: Page) {
  await page.goto("/automation/agents");
  for (const title of ["Knowledge answers", "Website chat"]) {
    const box = card(page, title);
    const on = box.getByLabel("Switched on");
    if (!(await on.isChecked())) await on.check();
    await box.getByLabel("Monthly token budget").fill("");
    for (const tool of await box.getByRole("checkbox").all())
      if (!(await tool.isChecked())) await tool.check();
    await box.getByRole("button", { name: "Save settings" }).click();
    await expect(page.getByText(/were saved/)).toBeVisible();
    await page.goto("/automation/agents");
  }
}

test("an admin switches, caps and narrows; a manager only reads; an agent cannot see it", async ({
  browser,
}) => {
  const adminPage = await (await browser.newContext()).newPage();
  await login(adminPage, USERS.admin);
  try {
    // The menu entry opens the page, and it lists the four agents.
    await adminPage.getByRole("link", { name: "AI agents" }).click();
    await expect(adminPage).toHaveURL(/\/automation\/agents$/);
    await expect(
      adminPage.getByRole("heading", { name: "AI agents" }),
    ).toBeVisible();
    for (const title of [
      "Staff assistant",
      "Customer portal assistant",
      "Website chat",
      "Knowledge answers",
    ])
      await expect(card(adminPage, title)).toBeVisible();

    // Switch knowledge answers off and give it a small budget.
    const knowledge = card(adminPage, "Knowledge answers");
    await knowledge.getByLabel("Switched on").uncheck();
    await knowledge.getByLabel("Monthly token budget").fill("5,000");
    await knowledge.getByRole("button", { name: "Save settings" }).click();
    await expect(
      adminPage.getByText("The settings of knowledge answers were saved."),
    ).toBeVisible();
    await expect(card(adminPage, "Knowledge answers")).toContainText(
      "Switched off",
    );
    await expect(card(adminPage, "Knowledge answers")).toContainText(
      "of 5,000 tokens used this month",
    );
    await expect(card(adminPage, "Knowledge answers")).not.toContainText(
      "(the standard limit)",
    );

    // Take the save-lead tool away from the website chat.
    const chat = card(adminPage, "Website chat");
    await chat.getByLabel("save_lead").uncheck();
    await chat.getByRole("button", { name: "Save settings" }).click();
    await expect(
      adminPage.getByText("The settings of website chat were saved."),
    ).toBeVisible();
    await expect(card(adminPage, "Website chat")).toContainText(
      "0 of 1 tools allowed",
    );

    // A bad budget is explained and what was typed is kept.
    await card(adminPage, "Knowledge answers")
      .getByLabel("Monthly token budget")
      .fill("lots");
    await card(adminPage, "Knowledge answers")
      .getByRole("button", { name: "Save settings" })
      .click();
    await expect(adminPage.getByText(/whole numbers only/i)).toBeVisible();
    await expect(
      card(adminPage, "Knowledge answers").getByLabel("Monthly token budget"),
    ).toHaveValue("lots");

    // A sales manager sees the same state but has no settings to change.
    const managerPage = await (await browser.newContext()).newPage();
    await login(managerPage, USERS.manager, "/automation/agents");
    await expect(card(managerPage, "Knowledge answers")).toContainText(
      "Switched off",
    );
    await expect(
      managerPage.getByRole("button", { name: "Save settings" }),
    ).toHaveCount(0);
    await expect(
      managerPage.getByText(/Only a tenant administrator can change/),
    ).toBeVisible();

    // An agent has no menu entry and the page says no.
    const agentPage = await (await browser.newContext()).newPage();
    await login(agentPage, USERS.agent1);
    await expect(
      agentPage.getByRole("link", { name: "AI agents" }),
    ).toHaveCount(0);
    await agentPage.goto("/automation/agents");
    await expect(
      agentPage.getByText(/not allowed|permission|don't have/i).first(),
    ).toBeVisible();
  } finally {
    await restore(adminPage);
  }

  // Everything is back: on, the standard limit, all tools.
  await expect(card(adminPage, "Knowledge answers")).toContainText("On");
  await expect(card(adminPage, "Knowledge answers")).toContainText(
    "(the standard limit)",
  );
  await expect(card(adminPage, "Website chat")).toContainText(
    "1 of 1 tools allowed",
  );
});
