import { expect, test, type Page } from "@playwright/test";

import { USERS, login, requireCredentials, uniqueName } from "./helpers";

/**
 * Buyer memory (ADR 0028), end to end: an agent copies the lead form in as facts, adds an
 * assumption with its reason, confirms it with the buyer's words, and sees that a fact without a
 * quote and a card number are refused; a colleague who may not read the lead sees nothing, a
 * manager reads it. A second journey (needs the website chat switched on, like public-chat.spec.ts)
 * shows that what a website visitor gave appears as facts citing the chat.
 * Creates clearly fictional "E2eMemory…" leads.
 */
test.beforeEach(() => requireCredentials());

const card = (page: Page) => page.getByRole("region", { name: "Buyer memory" });

async function newLead(page: Page): Promise<string> {
  const lastName = uniqueName("E2eMemory");
  await page.goto("/leads/new");
  await page.getByLabel(/Last name/).fill(lastName);
  await page.getByLabel(/Property type/).selectOption({ label: "Apartment" });
  await page.getByLabel(/Minimum budget/).fill("1.2 Cr");
  await page.getByLabel(/Maximum budget/).fill("1.5 Cr");
  await page.getByLabel(/Location/).fill("Kokapet, Hyderabad");
  await page.getByRole("button", { name: "Create lead" }).click();
  await page
    .getByRole("link", { name: new RegExp(lastName) })
    .first()
    .click();
  await page.waitForURL(/\/leads\/[0-9a-f-]{36}$/);
  return lastName;
}

async function addDetail(
  page: Page,
  what: string,
  how: "The buyer told us" | "We think so (not confirmed)",
  value: string,
  because: string,
) {
  const form = card(page);
  if (!(await form.getByLabel("What is it about?").isVisible()))
    await form.getByText("Add a detail").click();
  await form.getByLabel("What is it about?").selectOption({ label: what });
  await form.getByLabel(how).check();
  await form.getByLabel("The detail", { exact: true }).fill(value);
  if (how === "The buyer told us")
    await form.getByLabel("What the buyer said").fill(because);
  else await form.getByLabel("Why do we think so?").fill(because);
}

test("an agent builds up what we know about a buyer, fact by fact", async ({
  browser,
}) => {
  test.setTimeout(180_000);
  const agent = await (await browser.newContext()).newPage();
  await login(agent, USERS.agent1, "/leads/new");
  await newLead(agent);
  const leadUrl = agent.url();

  // 1. A new lead: nothing known, all twelve details are still to ask.
  await expect(card(agent)).toContainText(
    "0 facts · 0 assumptions · 12 still to ask",
  );
  await expect(card(agent)).toContainText("Nothing recorded yet");
  await expect(
    card(agent)
      .getByRole("region", { name: "Still to ask" })
      .getByRole("listitem"),
  ).toHaveCount(12);

  // 2. Copy the lead form: budget, property type and area become facts that cite the lead form.
  await card(agent)
    .getByRole("button", { name: "Copy from the lead form" })
    .click();
  await expect(
    agent.getByText(/The lead form was copied into the buyer memory/),
  ).toBeVisible();
  await expect(card(agent)).toContainText(
    "3 facts · 0 assumptions · 9 still to ask",
  );
  const facts = card(agent).getByRole("region", { name: "Facts" });
  await expect(facts).toContainText("1.2 Cr - 1.5 Cr");
  await expect(facts).toContainText("Apartment");
  await expect(facts).toContainText("Kokapet, Hyderabad");
  await expect(facts).toContainText("The lead form");

  // 3. An assumption needs a reason, and is not a fact.
  await addDetail(
    agent,
    "When they want to buy",
    "We think so (not confirmed)",
    "Within six months",
    "",
  );
  await card(agent).getByRole("button", { name: "Save detail" }).click();
  await expect(card(agent).getByText("Say why we think so.")).toBeVisible();
  await card(agent)
    .getByLabel("Why do we think so?")
    .fill("Sounded in a hurry on the phone");
  await card(agent).getByRole("button", { name: "Save detail" }).click();
  await expect(
    agent.getByText("The detail was added to the buyer memory."),
  ).toBeVisible();
  await expect(card(agent)).toContainText(
    "3 facts · 1 assumption · 8 still to ask",
  );
  const guesses = card(agent).getByRole("region", { name: "Assumptions" });
  await expect(guesses).toContainText("Within six months");
  await expect(guesses).toContainText(
    "Why we think so: Sounded in a hurry on the phone",
  );

  // 4. Confirming asks for the buyer's words and turns it into a fact; the guess stays in the history.
  await guesses.getByRole("button", { name: "Confirm" }).click();
  await card(agent).getByRole("button", { name: "Confirm as fact" }).click();
  await expect(
    card(agent).getByText("Write what the buyer said."),
  ).toBeVisible();
  await card(agent)
    .getByLabel("What did the buyer say?")
    .fill("We want to move in before June.");
  await card(agent).getByRole("button", { name: "Confirm as fact" }).click();
  await expect(agent.getByText(/The assumption was confirmed/)).toBeVisible();
  await expect(card(agent)).toContainText(
    "4 facts · 0 assumptions · 8 still to ask",
  );
  const factsNow = card(agent).getByRole("region", { name: "Facts" });
  await expect(factsNow).toContainText("Within six months");
  await expect(factsNow).toContainText("Buyer confirmed");
  await expect(factsNow).toContainText("We want to move in before June.");
  await expect(card(agent)).toContainText("Earlier entries (1)");

  // 5. A fact without the buyer's words, and a card number, are refused; nothing is added.
  await addDetail(agent, "Financing", "The buyer told us", "Home loan", "");
  await card(agent).getByRole("button", { name: "Save detail" }).click();
  await expect(
    card(agent).getByText("Write what the buyer said."),
  ).toBeVisible();
  await addDetail(
    agent,
    "Financing",
    "We think so (not confirmed)",
    "Card 4111 1111 1111 1111",
    "Said so",
  );
  await card(agent).getByRole("button", { name: "Save detail" }).click();
  await expect(card(agent).getByRole("alert")).toContainText(/card number/i);
  await expect(card(agent)).toContainText(
    "4 facts · 0 assumptions · 8 still to ask",
  );

  // 6. A colleague who may not read the lead gets nothing, not even the card.
  const other = await (await browser.newContext()).newPage();
  await login(other, USERS.agent2, "/");
  await other.goto(leadUrl);
  await expect(
    other.getByText(/Page not found|not found/i).first(),
  ).toBeVisible();
  await expect(card(other)).toHaveCount(0);

  // 7. A manager reads it - and sees that a fact cites its source.
  const manager = await (await browser.newContext()).newPage();
  await login(manager, USERS.manager, "/");
  await manager.goto(leadUrl);
  await expect(card(manager)).toContainText(
    "4 facts · 0 assumptions · 8 still to ask",
  );
  await expect(
    card(manager).getByRole("region", { name: "Facts" }),
  ).toContainText("We want to move in before June.");

  // 8. Support agents have no lead access: no card.
  const support = await (await browser.newContext()).newPage();
  await login(support, USERS.support, "/");
  await support.goto(leadUrl);
  await expect(card(support)).toHaveCount(0);
});

test("what a website visitor gave appears as facts that cite the chat", async ({
  browser,
}) => {
  test.skip(
    !process.env.PUBLIC_CHAT_SERVER_KEY,
    "PUBLIC_CHAT_SERVER_KEY is not set in .env.local (public chat switched off)",
  );
  test.setTimeout(150_000);
  const letters = Date.now()
    .toString(36)
    .replace(/\d/g, (d) => "abcdefghij"[Number(d)]);
  const lastName = "Memory" + letters;

  // A visitor without an account (each run a different documentation-only address).
  const address = `198.51.100.${1 + Math.floor(Math.random() * 254)}`;
  const visitor = await (
    await browser.newContext({
      extraHTTPHeaders: { "x-forwarded-for": address },
    })
  ).newPage();
  await visitor.goto("/chat");
  await visitor.getByLabel("Your message").fill("Hi, I want a 3BHK flat");
  await visitor.getByRole("button", { name: "Send" }).click();
  await expect(
    visitor.getByText(/your name and phone number\?/i),
  ).toBeVisible();
  await visitor
    .getByLabel("Your message")
    .fill(`I am Ravi ${lastName}, phone 98480 12345`);
  await visitor.getByRole("button", { name: "Send" }).click();
  await expect(visitor.getByRole("status")).toContainText(
    "passed on to our team",
  );

  // The manager opens the new lead and finds what the visitor gave as facts citing the chat.
  const manager = await (await browser.newContext()).newPage();
  await login(manager, USERS.manager, `/leads?q=${lastName}`);
  await manager
    .getByRole("link", { name: new RegExp(lastName) })
    .first()
    .click();
  await manager.waitForURL(/\/leads\/[0-9a-f-]{36}$/);
  const facts = card(manager).getByRole("region", { name: "Facts" });
  await expect(facts).toContainText("The website chat");
  await expect(facts).toContainText("Apartment");
  await expect(facts).toContainText("1.2 Cr - 1.5 Cr");
  await expect(facts).toContainText("Kokapet, Hyderabad");
  // Nothing was guessed: the other nine details are still to ask.
  await expect(card(manager)).toContainText(
    "3 facts · 0 assumptions · 9 still to ask",
  );
});
