import { expect, test, type Page } from "@playwright/test";

import { USERS, login, requireCredentials, uniqueName } from "./helpers";

/**
 * The video brief (ADR 0041), end to end: an agent opens it from the lead page, copies the lead
 * form into buyer memory so there are confirmed facts, changes the language / length / goal and sees
 * the script change, while an unconfirmed lead-form detail is shown but never spoken; a colleague
 * who may not read the lead and a support agent get "not found" or no button, and a manager can
 * open it. Creates a clearly fictional "E2eVideo…" lead. The quote prices are covered by the API
 * tests (a quote needs a converted lead).
 */
test.beforeEach(() => requireCredentials());

const section = (page: Page, name: string) =>
  page.getByRole("region", { name, exact: true });

test("an agent prepares the brief for a buyer video and it changes with the choices", async ({
  browser,
}) => {
  test.setTimeout(180_000);
  const lastName = uniqueName("E2eVideo");
  const agent = await (await browser.newContext()).newPage();
  await login(agent, USERS.agent1, "/leads/new");

  await agent.getByLabel(/First name/).fill("Suresh");
  await agent.getByLabel(/Last name/).fill(lastName);
  await agent.getByLabel(/E-mail/).fill("video.buyer@example.test");
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

  // 1. With nothing confirmed yet, the brief shows the lead form but says nothing from it.
  await agent.getByRole("link", { name: "Video brief" }).click();
  await agent.waitForURL(new RegExp(`/print/leads/${leadId}/video-brief`));
  await expect(agent.getByRole("heading", { level: 1 })).toHaveText(
    "Video brief",
  );
  const script = section(agent, "The script");
  await expect(script).toContainText("Hello Suresh,");
  await expect(script.getByText("Fact", { exact: true })).toHaveCount(0);
  await expect(section(agent, "What it is built from")).toContainText(
    "Lead form",
  );
  await expect(section(agent, "Be careful")).toContainText(
    "No confirmed buyer facts yet",
  );
  // The buyer's phone number and e-mail are never in the brief.
  await expect(agent.locator("article")).not.toContainText("98480");
  await expect(agent.locator("article")).not.toContainText(
    "video.buyer@example.test",
  );

  // 2. Confirm the lead form in buyer memory: now there are facts to say.
  await agent.goto(leadUrl);
  const memory = agent.getByRole("region", { name: "Buyer memory" });
  await memory.getByRole("button", { name: "Copy from the lead form" }).click();
  await expect(memory).toContainText("3 facts");
  await agent.goto(`/print/leads/${leadId}/video-brief`);
  await expect(
    section(agent, "The script").getByText("Fact", { exact: true }),
  ).toHaveCount(3);
  await expect(section(agent, "The script")).toContainText("Kokapet");

  // 3. Hindi, 30 seconds, "after a site visit": the script changes language and length.
  await agent.getByLabel("Language").selectOption({ label: "Hindi" });
  await agent.getByLabel("Length").selectOption({ label: "30 seconds" });
  await agent
    .getByLabel("What is the video for?")
    .selectOption({ label: "After a site visit" });
  await agent.getByRole("button", { name: "Update the brief" }).click();
  await expect(agent).toHaveURL(/language=hi/);
  await expect(section(agent, "The script")).toContainText("नमस्ते Suresh जी");
  await expect(agent.getByText(/native speaker/)).toBeVisible();
  await expect(section(agent, "The script")).toContainText(
    /30 seconds holds about 75/,
  );

  // 4. A changed address cannot send anything odd: an unknown value falls back to the default.
  await agent.goto(
    `/print/leads/${leadId}/video-brief?goal=spam&tone=angry&length=45&language=fr`,
  );
  await expect(section(agent, "The script")).toContainText(
    /60 seconds holds about 150/,
  );

  // 5. The lists the person must follow are on the page.
  await expect(section(agent, "Never say this")).toContainText("guaranteed");
  await expect(section(agent, "Say this")).toContainText("RERA");

  // 6. A colleague who may not read the lead gets "not found"; a manager can open it.
  const other = await (await browser.newContext()).newPage();
  await login(other, USERS.agent2, "/");
  await other.goto(`/print/leads/${leadId}/video-brief`);
  await expect(other.getByText(/not found/i).first()).toBeVisible();
  await expect(other.getByRole("heading", { name: "Video brief" })).toHaveCount(
    0,
  );
  const manager = await (await browser.newContext()).newPage();
  await login(manager, USERS.manager, "/");
  await manager.goto(`/print/leads/${leadId}/video-brief`);
  await expect(section(manager, "The script")).toContainText("Hello Suresh,");

  // 7. Support agents have no lead access: no brief.
  const support = await (await browser.newContext()).newPage();
  await login(support, USERS.support, "/");
  await support.goto(`/print/leads/${leadId}/video-brief`);
  await expect(
    support.getByRole("heading", { name: "Video brief" }),
  ).toHaveCount(0);
});
