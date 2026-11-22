import { expect, test } from "@playwright/test";

import { USERS, login, requireCredentials, uniqueName } from "./helpers";

/**
 * Writing and saving a buyer-video script (ADR 0041, VB3), end to end: an agent edits the suggested
 * script and saves it (version 1), a phone number and a banned statement are refused with plain
 * words and the typed text stays, a second save is version 2 and comes first in the list, and a
 * manager sees the saved scripts while a colleague who may not read the lead gets "not found".
 * Creates a clearly fictional "E2eScript…" lead.
 */
test.beforeEach(() => requireCredentials());

test("an agent edits, saves and re-saves a script and the refusals keep the text", async ({
  browser,
}) => {
  test.setTimeout(180_000);
  const lastName = uniqueName("E2eScript");
  const agent = await (await browser.newContext()).newPage();
  await login(agent, USERS.agent1, "/leads/new");
  await agent.getByLabel(/First name/).fill("Suresh");
  await agent.getByLabel(/Last name/).fill(lastName);
  await agent.getByRole("button", { name: "Create lead" }).click();
  await agent
    .getByRole("link", { name: new RegExp(lastName) })
    .first()
    .click();
  await agent.waitForURL(/\/leads\/[0-9a-f-]{36}$/);
  const leadId = agent.url().split("/").pop() as string;
  const url = `/print/leads/${leadId}/video-brief`;

  // 1. The editor starts from the suggested script; nothing is saved yet.
  await agent.goto(url);
  const box = agent.getByLabel(/Your script/);
  await expect(box).toHaveValue(/Hello Suresh,/);
  await expect(agent.getByText("No script saved yet.")).toBeVisible();

  // 2. Save it as it is, with one sentence changed: version 1.
  await box.fill("Hello Suresh,\nHere is my first version.\nThank you.");
  await agent.getByRole("button", { name: "Save script" }).click();
  await expect(agent.getByRole("status")).toContainText("version 1");
  const saved = agent.getByRole("region", { name: "Saved scripts" });
  await expect(saved).toContainText("Version 1");
  await expect(saved).toContainText("Here is my first version.");

  // 3. A phone number is refused in plain words and the typed text stays.
  const again = agent.getByLabel(/Your script/);
  await again.fill("Hello Suresh,\nCall me on 98480 12345.");
  await agent.getByRole("button", { name: "Save script" }).click();
  await expect(agent.getByText("Could not save").locator("..")).toContainText(
    /phone number/i,
  );
  await expect(agent.getByLabel(/Your script/)).toHaveValue(
    "Hello Suresh,\nCall me on 98480 12345.",
  );

  // 4. A banned statement is refused too.
  await agent
    .getByLabel(/Your script/)
    .fill("Hello Suresh,\nThis flat is a guaranteed return.");
  await agent.getByRole("button", { name: "Save script" }).click();
  await expect(agent.getByText("Could not save").locator("..")).toContainText(
    /never-say list/i,
  );

  // 5. A good second save is version 2 and comes first.
  await agent
    .getByLabel(/Your script/)
    .fill("Hello Suresh,\nHere is my second version.");
  await agent.getByRole("button", { name: "Save script" }).click();
  await expect(agent.getByRole("status")).toContainText("version 2");
  const items = agent
    .getByRole("region", { name: "Saved scripts" })
    .getByRole("listitem", { name: /Version/ });
  await expect(items).toHaveCount(2);
  await expect(items.first()).toContainText("Version 2");
  await expect(items.first()).toContainText("second version");

  // 6. A manager sees the saved scripts; a colleague who may not read the lead gets "not found".
  const manager = await (await browser.newContext()).newPage();
  await login(manager, USERS.manager, "/");
  await manager.goto(url);
  await expect(
    manager.getByRole("region", { name: "Saved scripts" }),
  ).toContainText("Version 2");
  const other = await (await browser.newContext()).newPage();
  await login(other, USERS.agent2, "/");
  await other.goto(url);
  await expect(other.getByText(/not found/i).first()).toBeVisible();
  await expect(
    other.getByRole("region", { name: "Saved scripts" }),
  ).toHaveCount(0);
});
