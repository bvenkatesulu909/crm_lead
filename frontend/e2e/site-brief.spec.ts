import { expect, test, type Page } from "@playwright/test";

import { USERS, login, requireCredentials, uniqueName } from "./helpers";

/**
 * The rep's brief before a site visit (ADR 0029), end to end: an agent opens the brief from the lead
 * page, sees what is still to ask, fills in buyer memory and watches the brief change, types a place
 * (a card number in it is refused with a sentence and the brief still shows), and a colleague who
 * may not read the lead - and a support agent - get "not found". Creates a clearly fictional
 * "E2eBrief…" lead.
 */
test.beforeEach(() => requireCredentials());

const section = (page: Page, name: string) =>
  page.getByRole("region", { name, exact: true });

test("an agent opens the brief, fills in what they learn and sees it change", async ({
  browser,
}) => {
  test.setTimeout(180_000);
  const lastName = uniqueName("E2eBrief");
  const agent = await (await browser.newContext()).newPage();
  await login(agent, USERS.agent1, "/leads/new");

  await agent.getByLabel(/Last name/).fill(lastName);
  await agent.getByLabel(/E-mail/).fill("brief.buyer@example.test");
  await agent.getByLabel(/Phone/).fill("98480 12345");
  await agent.getByLabel(/Property type/).selectOption({ label: "Apartment" });
  await agent.getByLabel(/Minimum budget/).fill("1.2 Cr");
  await agent.getByLabel(/Maximum budget/).fill("1.5 Cr");
  await agent.getByLabel(/Location/).fill("Kokapet, Hyderabad");
  await agent.getByRole("button", { name: "Create lead" }).click();
  await agent
    .getByRole("link", { name: new RegExp(lastName) })
    .first()
    .click();
  await agent.waitForURL(/\/leads\/[0-9a-f-]{36}$/);
  const leadUrl = agent.url();
  const leadId = leadUrl.split("/").pop() as string;

  // 1. The button on the lead page opens the brief.
  await agent.getByRole("link", { name: "Site visit brief" }).click();
  await agent.waitForURL(new RegExp(`/print/leads/${leadId}/brief$`));
  await expect(agent.getByRole("heading", { level: 1 })).toHaveText(
    "Site visit brief",
  );
  await expect(agent.getByText(/As of /)).toBeVisible();
  const buyer = section(agent, "The buyer");
  await expect(buyer).toContainText(lastName);
  await expect(buyer).toContainText("98480 12345");
  await expect(buyer).toContainText("brief.buyer@example.test");

  // 2. Nothing is known yet: twelve questions, and the lead form holds details memory does not.
  await expect(section(agent, "What we know")).toContainText(
    "Nothing recorded yet",
  );
  await expect(
    section(agent, "Ask on the visit").getByRole("listitem"),
  ).toHaveCount(12);
  await expect(section(agent, "Be careful")).toContainText("The lead form has");
  await expect(section(agent, "Where we left off")).toContainText(
    "Nothing logged on this lead yet",
  );
  await expect(section(agent, "Where we left off")).toContainText(
    "No open follow-ups",
  );

  // 3. Fill in buyer memory on the lead page: copy the lead form, add an assumption.
  await agent.goto(leadUrl);
  const memory = agent.getByRole("region", { name: "Buyer memory" });
  await memory.getByRole("button", { name: "Copy from the lead form" }).click();
  await expect(memory).toContainText(
    "3 facts · 0 assumptions · 9 still to ask",
  );
  await memory.getByText("Add a detail").click();
  await memory
    .getByLabel("What is it about?")
    .selectOption({ label: "When they want to buy" });
  await memory.getByLabel("We think so (not confirmed)").check();
  await memory
    .getByLabel("The detail", { exact: true })
    .fill("Within six months");
  await memory
    .getByLabel("Why do we think so?")
    .fill("Sounded in a hurry on the phone");
  await memory.getByRole("button", { name: "Save detail" }).click();
  await expect(memory).toContainText("3 facts · 1 assumption · 8 still to ask");

  // 4. The brief now shows facts and the assumption to confirm, and asks only what is missing.
  await agent.goto(`/print/leads/${leadId}/brief`);
  const known = section(agent, "What we know");
  await expect(known).toContainText("1.2 Cr - 1.5 Cr");
  await expect(known).toContainText("Apartment");
  await expect(known).toContainText("The lead form");
  await expect(known).toContainText("Within six months");
  await expect(known).toContainText("Sounded in a hurry on the phone");
  await expect(known.getByText("Fact", { exact: true })).toHaveCount(3);
  await expect(known.getByText("Assumption", { exact: true })).toHaveCount(1);
  const ask = section(agent, "Ask on the visit").getByRole("listitem");
  await expect(ask).toHaveCount(9); // one to confirm + eight still unknown
  await expect(ask.first()).toContainText("Confirm");
  await expect(ask.first()).toContainText("Within six months");
  await expect(section(agent, "Be careful")).not.toContainText(
    "The lead form has",
  );

  // 5. A place typed for this view is shown; a card number in it is refused, the brief still shows.
  await agent.getByLabel("Where is the visit?").fill("Skyline Towers, tower B");
  await agent.getByRole("button", { name: "Update" }).click();
  await expect(
    agent.getByText("Visit at: Skyline Towers, tower B"),
  ).toBeVisible();
  await agent
    .getByLabel("Where is the visit?")
    .fill("card 4111 1111 1111 1111");
  await agent.getByRole("button", { name: "Update" }).click();
  await expect(agent.getByRole("alert")).toContainText(/refused/i);
  await expect(section(agent, "The buyer")).toBeVisible();
  await expect(agent.getByText(/Visit at:/)).toHaveCount(0);

  // 6. A colleague who may not read the lead gets "not found"; a manager reads it.
  const other = await (await browser.newContext()).newPage();
  await login(other, USERS.agent2, "/");
  await other.goto(`/print/leads/${leadId}/brief`);
  await expect(other.getByText(/not found/i).first()).toBeVisible();
  await expect(
    other.getByRole("heading", { name: "Site visit brief" }),
  ).toHaveCount(0);
  const manager = await (await browser.newContext()).newPage();
  await login(manager, USERS.manager, "/");
  await manager.goto(`/print/leads/${leadId}/brief`);
  await expect(section(manager, "What we know")).toContainText(
    "Within six months",
  );

  // 7. Support agents have no lead access: no brief, and no button on a lead page they cannot open.
  const support = await (await browser.newContext()).newPage();
  await login(support, USERS.support, "/");
  await support.goto(`/print/leads/${leadId}/brief`);
  await expect(
    support.getByRole("heading", { name: "Site visit brief" }),
  ).toHaveCount(0);
});
