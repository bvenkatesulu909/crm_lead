import { execFileSync } from "node:child_process";
import path from "node:path";

import { expect, test } from "@playwright/test";

import { USERS, login, requireCredentials } from "./helpers";

/**
 * Public website chat (ADR 0013, BP-01), end to end with the FAKE model: a visitor without an
 * account chats on /chat and leaves their details; the lead lands in the CRM, sales managers are
 * notified, and staff who may see the lead read the conversation on the lead page.
 *
 * Needs the chat switched on locally: CRM_PUBLIC_CHAT_TENANT_SLUG=alpha-demo,
 * CRM_PUBLIC_CHAT_PROVIDER=fake and CRM_PUBLIC_CHAT_SERVER_KEY in backend/.env, and the same key
 * as PUBLIC_CHAT_SERVER_KEY in frontend/.env.local (see docs/public-chat.md). Creates a clearly
 * fictional "Ravi Chat…" lead.
 */
test.beforeEach(() => {
  requireCredentials();
  test.skip(
    !process.env.PUBLIC_CHAT_SERVER_KEY,
    "PUBLIC_CHAT_SERVER_KEY is not set in .env.local (public chat switched off)",
  );
});

function runWorkerOnce() {
  execFileSync(path.join("..", "backend", ".venv", "Scripts", "python.exe"), ["-m", "app.worker", "--once"], {
    cwd: path.join("..", "backend"), timeout: 60_000, stdio: "ignore",
  });
} // prettier-ignore

/** Letters only: the fake model reads names made of letters. */
function uniqueLetters() {
  return Date.now()
    .toString(36)
    .replace(/\d/g, (d) => "abcdefghij"[Number(d)]);
}

test("a website visitor's details become a lead that managers hear about", async ({
  browser,
}) => {
  test.setTimeout(150_000);
  const lastName = "Chat" + uniqueLetters();
  const fullName = `Ravi ${lastName}`;

  // 1. A visitor without an account: no sign-in, a privacy notice, plain-text answers. Each
  // run is a different visitor (a documentation-only address), so the per-address limit of
  // 3 new conversations an hour doesn't stop repeated runs.
  const address = `198.51.100.${1 + Math.floor(Math.random() * 254)}`;
  const visitor = await (
    await browser.newContext({
      extraHTTPHeaders: { "x-forwarded-for": address },
    })
  ).newPage();
  await visitor.goto("/chat");
  await expect(visitor).toHaveURL(/\/chat$/); // not sent to /login
  await expect(
    visitor.getByText(/stored to answer your enquiry/),
  ).toBeVisible();
  const box = visitor.getByLabel("Your message");
  await box.fill("Hi, I want a 3BHK flat");
  await visitor.getByRole("button", { name: "Send" }).click();
  await expect(
    visitor.getByText(/your name and phone number\?/i),
  ).toBeVisible();
  await box.fill(`I am ${fullName}, phone 98480 12345`);
  await visitor.getByRole("button", { name: "Send" }).click();
  await expect(visitor.getByRole("status")).toContainText(
    "passed on to our team",
  );
  // The conversation token is an httpOnly cookie: page JavaScript can't read it.
  expect(await visitor.evaluate(() => document.cookie)).not.toContain(
    "crm_chat",
  );

  // 2. The worker turns the event into notifications for the sales managers.
  runWorkerOnce();
  const manager = await (await browser.newContext()).newPage();
  await login(manager, USERS.manager, "/notifications");
  const note = manager.getByRole("button", {
    name: new RegExp(`New lead from the website chat: ${fullName}`),
  });
  await expect(note).toBeVisible();
  await note.click();
  await expect(manager.getByRole("heading", { level: 1 })).toHaveText(fullName);

  // 3. The lead page shows the conversation for staff who may read the lead.
  const chat = manager.getByRole("region", { name: "Website chat" });
  await expect(chat).toContainText("Hi, I want a 3BHK flat");
  await expect(chat).toContainText(`I am ${fullName}, phone 98480 12345`);
  await expect(chat.getByRole("listitem")).toHaveCount(4);
  const leadUrl = manager.url();

  // 4. An agent may not see an unassigned lead - nor its conversation.
  const agent = await (await browser.newContext()).newPage();
  await login(agent, USERS.agent1, "/");
  await agent.goto(leadUrl);
  await expect(
    agent.getByText(/not found|doesn't exist/i).first(),
  ).toBeVisible();
  await expect(agent.getByRole("region", { name: "Website chat" })).toHaveCount(
    0,
  );
});

test("bots that fill the hidden field are refused", async ({ request }) => {
  const response = await request.post("/api/public-chat", {
    data: {
      message: "Cheap followers at spam.example.test",
      website: "http://spam.example.test",
    },
  });
  expect(response.status()).toBe(422);
  expect((await response.json()).code).toBe("message_refused");
});
