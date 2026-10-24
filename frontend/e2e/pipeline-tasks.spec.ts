import { expect, test, type Browser, type Page } from "@playwright/test";

import { USERS, login, requireCredentials, uniqueName } from "./helpers";

/**
 * Phase D: opportunity pipeline (create, Kanban moves, won/lost, reopen) and activities
 * (follow-ups, reminders bell, logging, calendar) - against the running backend.
 * Creates clearly fictional "E2e…" records.
 */
test.beforeEach(() => requireCredentials());

async function signedIn(browser: Browser, user: string, target = "/") {
  const page = await (await browser.newContext()).newPage();
  await login(page, user, target);
  return page;
}

async function newAccount(page: Page, name: string) {
  await page.goto("/accounts/new");
  await page.getByLabel("Name").fill(name);
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByText("The account was created.")).toBeVisible({
    timeout: 20_000,
  });
  return page.url().split("/accounts/")[1].split("?")[0];
}

async function newDeal(
  page: Page,
  accountId: string,
  name: string,
  amount = "",
) {
  await page.goto(`/opportunities/new?account=${accountId}`);
  await page.getByLabel("Name").fill(name);
  if (amount) await page.getByLabel(/Estimated value/).fill(amount);
  await page.getByRole("button", { name: "Create opportunity" }).click();
  // The new page renders after the redirect; the first render can take a few seconds.
  await expect(page.getByText("The opportunity was created.")).toBeVisible({
    timeout: 20_000,
  });
  return page.url().split("/opportunities/")[1].split("?")[0];
}

const column = (page: Page, stage: string) =>
  page.getByRole("region", { name: `${stage} column` });

/** "YYYY-MM-DDTHH:mm" for a datetime-local input, `days` from now at 10:00 local. */
function localDay(days: number, hour = 10) {
  const d = new Date();
  d.setDate(d.getDate() + days);
  d.setHours(hour, 0, 0, 0);
  const pad = (n: number) => String(n).padStart(2, "0");
  return {
    value: `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(hour)}:00`,
    month: `${d.getFullYear()}-${pad(d.getMonth() + 1)}`,
  };
}

test("a sales rep moves a deal through the pipeline to won", async ({
  page,
}, testInfo) => {
  await login(page, USERS.agent1);
  const accountId = await newAccount(page, uniqueName("E2eDealCo"));
  const deal = uniqueName("E2eDeal");
  await newDeal(page, accountId, deal);
  await expect(
    page.getByRole("list", { name: "Pipeline stage" }).getByText("Prospecting"),
  ).toHaveAttribute("aria-current", "step");

  // Stage dialog on the deal page.
  await page.getByRole("button", { name: "Move stage" }).click();
  await page
    .getByRole("dialog")
    .getByLabel("New stage")
    .selectOption("proposal");
  await page.getByRole("dialog").getByRole("button", { name: "Move" }).click();
  await expect(
    page.getByText("The deal moved to its new stage."),
  ).toBeVisible();

  // Kanban: the card is in Proposal; "Move to…" puts it in Negotiation.
  await page.goto(`/opportunities?q=${deal}`);
  const card = page.getByTestId("deal-card").filter({ hasText: deal });
  await expect(
    column(page, "Proposal").getByRole("link", { name: deal }),
  ).toBeVisible();
  await card.getByLabel(`Move ${deal} to`).selectOption("negotiation");
  await expect(
    column(page, "Negotiation").getByRole("link", { name: deal }),
  ).toBeVisible();
  await page.screenshot({
    path: testInfo.outputPath("board.png"),
    fullPage: true,
  });

  // Drag and drop back to Qualification.
  await column(page, "Negotiation")
    .getByTestId("deal-card")
    .filter({ hasText: deal })
    .dragTo(column(page, "Qualification"));
  await expect(
    column(page, "Qualification").getByRole("link", { name: deal }),
  ).toBeVisible();

  // Won needs a value.
  await page.getByRole("link", { name: deal }).click();
  await page.getByRole("button", { name: "Mark as won" }).click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Mark as won" })
    .click();
  await expect(
    page
      .getByRole("dialog")
      .getByText(/Add the deal value/)
      .first(),
  ).toBeVisible();
  await page.goto(page.url().split("?")[0] + "/edit");
  await page.getByLabel(/Estimated value/).fill("1500.50");
  await page.getByRole("button", { name: "Save changes" }).click();
  await expect(page.getByText("Your changes were saved.")).toBeVisible();
  await expect(page.getByText("€1,500.50").first()).toBeVisible();
  await page.getByRole("button", { name: "Mark as won" }).click();
  await page.getByRole("dialog").getByLabel(/Note/).fill("Contract signed");
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Mark as won" })
    .click();
  await expect(page.getByText("The deal was marked as won.")).toBeVisible();
  await expect(page.getByRole("link", { name: "Edit" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Reopen" })).toHaveCount(0); // agents can't
  await expect(page.getByText("Qualification → Won")).toBeVisible();
  await page.screenshot({
    path: testInfo.outputPath("deal.png"),
    fullPage: true,
  });
});

test("lost deals need a reason, and only managers reopen them", async ({
  browser,
}) => {
  const agent = await signedIn(browser, USERS.agent1);
  const accountId = await newAccount(agent, uniqueName("E2eLostCo"));
  const dealId = await newDeal(agent, accountId, uniqueName("E2eLost"), "200");
  await agent.getByRole("button", { name: "Mark as lost" }).click();
  const dialog = agent.getByRole("dialog");
  await dialog.getByRole("button", { name: "Mark as lost" }).click();
  await expect(
    dialog.getByText("Please say why the deal was lost."),
  ).toBeVisible();
  await dialog.getByLabel("Reason").fill("Chose a cheaper competitor");
  await dialog.getByRole("button", { name: "Mark as lost" }).click();
  await expect(
    agent.getByText("Chose a cheaper competitor").first(),
  ).toBeVisible();

  const manager = await signedIn(
    browser,
    USERS.manager,
    `/opportunities/${dealId}`,
  );
  await manager.getByRole("button", { name: "Reopen" }).click();
  await manager
    .getByRole("dialog")
    .getByLabel("Back to stage")
    .selectOption("proposal");
  await manager
    .getByRole("dialog")
    .getByRole("button", { name: "Reopen deal" })
    .click();
  await expect(manager.getByText("The deal is open again.")).toBeVisible();
  await expect(
    manager.getByRole("list", { name: "Pipeline stage" }).getByText("Proposal"),
  ).toHaveAttribute("aria-current", "step");
});

test("follow-ups: overdue task rings the bell, shows in Tasks and is completed", async ({
  page,
}) => {
  await login(page, USERS.agent2);
  const accountId = await newAccount(page, uniqueName("E2eTaskCo"));
  const bell = page.getByRole("link", { name: /^Tasks: / });
  const before = Number(
    (await bell.getAttribute("aria-label"))?.match(/\d+/)?.[0] ?? 0,
  );

  const subject = uniqueName("E2eCallBack");
  await page.getByLabel("Subject").fill(subject);
  await page.getByLabel("Type").selectOption("call");
  await page.getByLabel("Due (optional)").fill(localDay(-1).value);
  await page.getByLabel("Priority").selectOption("high");
  await page.getByRole("button", { name: "Add to tasks" }).click();
  await expect(page.getByText("The task was added.")).toBeVisible();
  const item = page.getByTestId("activity-item").filter({ hasText: subject });
  await expect(item.getByText("Overdue", { exact: true })).toBeVisible();
  await expect(item.getByText(/Overdue by/)).toBeVisible();
  await expect(bell).toHaveAttribute(
    "aria-label",
    `Tasks: ${before + 1} need${before + 1 === 1 ? "s" : ""} attention`,
  );

  // Log something that happened on the same account.
  await page.getByText("Log what happened").click();
  await page.getByLabel("Subject").fill("Intro meeting");
  await page.getByLabel("Type").selectOption("meeting");
  await page.locator("#act-outcome").fill("Wants a quote");
  await page.getByRole("button", { name: "Log activity" }).click();
  await expect(page.getByText("The activity was logged.")).toBeVisible();
  await expect(page.getByText("Outcome: Wants a quote")).toBeVisible();

  // Tasks page: in the Overdue group; mark it done.
  await page.goto("/tasks");
  const overdue = page.getByRole("region", { name: /^Overdue/ });
  await expect(overdue.getByText(subject, { exact: true })).toBeVisible();
  const row = page.getByTestId("activity-item").filter({ hasText: subject });
  await row.getByRole("button", { name: "Done" }).click();
  await page
    .getByRole("dialog")
    .getByLabel(/Outcome/)
    .fill("Left a voicemail");
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Mark as done" })
    .click();
  await expect(page.getByText("Marked as done.")).toBeVisible();
  await expect(
    page.getByRole("region", { name: /^Overdue/ }).getByText(subject),
  ).toHaveCount(0);
  await expect(
    page
      .getByTestId("activity-item")
      .filter({ hasText: subject })
      .getByText("Outcome: Left a voicemail"),
  ).toBeVisible();
  await expect(bell).toHaveAttribute(
    "aria-label",
    before === 0 ? "Tasks: nothing urgent" : /Tasks: \d+ need/,
  );
  void accountId;
});

test("the calendar shows a planned meeting on its day", async ({
  page,
}, testInfo) => {
  await login(page, USERS.agent1, "/tasks");
  const subject = uniqueName("E2eMeeting");
  const when = localDay(2, 14);
  await page.getByLabel("Subject").fill(subject);
  await page.getByLabel("Type").selectOption("meeting");
  await page.getByLabel("Due (optional)").fill(when.value);
  await page.getByRole("button", { name: "Add to tasks" }).click();
  await expect(page.getByText("The task was added.")).toBeVisible();
  await expect(
    page
      .getByRole("region", { name: /^Upcoming/ })
      .getByText(subject, { exact: true }),
  ).toBeVisible();

  await page.goto(`/tasks/calendar?month=${when.month}`);
  const cell = page.getByRole("cell").filter({ hasText: subject });
  await expect(
    cell.getByRole("link", { name: new RegExp(subject) }),
  ).toBeVisible();
  // At 14:00 local time (shown as 14:00 or 2:00 PM depending on the browser's locale).
  await expect(
    cell.getByRole("link", { name: new RegExp(subject) }),
  ).toHaveText(/(14|0?2):00/);
  await page.screenshot({
    path: testInfo.outputPath("calendar.png"),
    fullPage: true,
  });
});

test("lead pages plan follow-ups only; support can't open the pipeline", async ({
  browser,
}) => {
  const agent = await signedIn(browser, USERS.agent1, "/leads/new");
  const lastName = uniqueName("E2eLeadTask");
  await agent.getByLabel(/Last name/).fill(lastName);
  await agent.getByRole("button", { name: "Create lead" }).click();
  await agent.getByRole("link", { name: lastName }).click();
  await expect(
    agent.getByRole("heading", { name: "Tasks and follow-ups" }),
  ).toBeVisible();
  await expect(agent.getByText("Log what happened")).toHaveCount(0);

  const support = await signedIn(browser, USERS.support, "/opportunities");
  await expect(
    support.getByText("You don't have access to this page"),
  ).toBeVisible();
});
