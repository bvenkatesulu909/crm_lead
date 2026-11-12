import { expect, test, type Browser, type Page } from "@playwright/test";

import { USERS, login, requireCredentials } from "./helpers";

/**
 * The website chat in Hindi and Telugu (ADR 0027, BP-01 follow-up), end to end with the FAKE model:
 * a visitor picks a language, speaks (a faked browser speech engine hands back the words), the
 * details become a lead that carries the language, and a manager finds it with the "Call in"
 * filter. Phone numbers written in Hindi or Telugu digits are saved as 0-9.
 *
 * Needs the same switches as public-chat.spec.ts (CRM_PUBLIC_CHAT_PROVIDER=fake, the server key in
 * both .env files). Creates clearly fictional "Ravi Hindi…" / "Ravi Telugu…" leads.
 */
test.beforeEach(() => {
  requireCredentials();
  test.skip(
    !process.env.PUBLIC_CHAT_SERVER_KEY,
    "PUBLIC_CHAT_SERVER_KEY is not set in .env.local (public chat switched off)",
  );
});

/** Letters only: the fake model reads names made of letters. */
function uniqueLetters() {
  return Date.now()
    .toString(36)
    .replace(/\d/g, (d) => "abcdefghij"[Number(d)]);
}

/**
 * A visitor's browser with a faked speech engine: start() "hears" `heard` in whatever language
 * it was asked for, speechSynthesis records what it was told to say. Real engines differ per
 * browser; this checks OUR code (the language asked for, the words landing in the box).
 */
async function visitorPage(browser: Browser, heard: string): Promise<Page> {
  const address = `198.51.100.${1 + Math.floor(Math.random() * 254)}`;
  const context = await browser.newContext({
    extraHTTPHeaders: { "x-forwarded-for": address },
  });
  await context.addInitScript((words: string) => {
    const w = window as unknown as Record<string, unknown>;
    w.__heardLang = "";
    w.__spoken = [];
    class FakeRecognition {
      lang = "";
      continuous = false;
      interimResults = false;
      onresult: ((e: unknown) => void) | null = null;
      onend: (() => void) | null = null;
      onerror: (() => void) | null = null;
      start() {
        w.__heardLang = this.lang;
        setTimeout(() => {
          this.onresult?.({
            results: {
              length: 1,
              0: { 0: { transcript: words }, isFinal: true },
            },
          });
          this.onend?.();
        }, 50);
      }
      stop() {
        this.onend?.();
      }
    }
    // Current Chromium has both names and our code prefers the unprefixed one: fake both.
    w.SpeechRecognition = FakeRecognition;
    w.webkitSpeechRecognition = FakeRecognition;
    const synth = window.speechSynthesis;
    synth.speak = (u: SpeechSynthesisUtterance) => {
      (w.__spoken as { text: string; lang: string }[]).push({
        text: u.text,
        lang: u.lang,
      });
    };
  }, heard);
  return context.newPage();
}

async function managerFindsLead(
  browser: Browser,
  code: "hi" | "te",
  lastName: string,
): Promise<Page> {
  const manager = await (await browser.newContext()).newPage();
  await login(manager, USERS.manager, `/leads?language=${code}&q=${lastName}`);
  await manager
    .getByRole("link", { name: new RegExp(lastName) })
    .first()
    .click();
  await manager.waitForURL(/\/leads\/[0-9a-f-]{36}$/);
  return manager;
}

const field = (page: Page, name: string) =>
  page
    .getByRole("term")
    .filter({ hasText: new RegExp(`^${name}$`) })
    .locator("+ dd");

test("a Hindi speaker talks to the chat and the lead says to call in Hindi", async ({
  browser,
}) => {
  test.setTimeout(150_000);
  const lastName = "Hindi" + uniqueLetters();
  const visitor = await visitorPage(
    browser,
    `I am Ravi ${lastName}, फ़ोन ९८४८० १२३४५`,
  );
  await visitor.goto("/chat");
  await expect(
    visitor.getByText(/Hello! I can help you find a home/),
  ).toBeVisible();

  const group = visitor.getByRole("group", { name: "Language" });
  await expect(group).toContainText("English");
  await expect(group).toContainText("हिन्दी");
  await expect(group).toContainText("తెలుగు");
  await group.getByRole("button", { name: "हिन्दी" }).click();
  await expect(visitor.getByText(/नमस्ते!/)).toBeVisible();
  await expect(visitor.getByRole("button", { name: "भेजें" })).toBeVisible();

  // Reading aloud is off until the visitor ticks it; the voice notice is shown.
  const readAloud = visitor.getByLabel("जवाब बोलकर सुनाएँ");
  await expect(readAloud).not.toBeChecked();
  await expect(visitor.getByText(/ब्राउज़र की स्पीच सेवा/)).toBeVisible();
  await readAloud.check();

  // Speak: the words land in the message box, in the language asked for; nothing is sent yet.
  await visitor.getByRole("button", { name: "बोलें" }).click();
  const box = visitor.getByLabel("आपका संदेश");
  await expect(box).toHaveValue(new RegExp(`Ravi ${lastName}`));
  expect(
    await visitor.evaluate(
      () => (window as unknown as { __heardLang: string }).__heardLang,
    ),
  ).toBe("hi-IN");
  await expect(visitor.getByRole("status")).toHaveCount(0);

  await visitor.getByRole("button", { name: "भेजें" }).click();
  await expect(visitor.getByRole("status")).toContainText(
    "हमारी टीम को भेज दी गई है",
  );
  const spoken = await visitor.evaluate(
    () => (window as unknown as { __spoken: { lang: string }[] }).__spoken,
  );
  expect(spoken.length).toBeGreaterThan(0);
  expect(spoken[0].lang).toBe("hi-IN");

  // The manager finds the lead with the Call-in filter; the phone number is 0-9.
  const manager = await managerFindsLead(browser, "hi", lastName);
  await expect(field(manager, "Call in")).toHaveText("Hindi");
  await expect(field(manager, "Phone")).toHaveText("98480 12345");
  await manager.goto(`/leads?language=te&q=${lastName}`);
  await expect(
    manager.getByRole("link", { name: new RegExp(lastName) }),
  ).toHaveCount(0);
});

test("a Telugu speaker types digits in Telugu and the lead says to call in Telugu", async ({
  browser,
}) => {
  test.setTimeout(150_000);
  const lastName = "Telugu" + uniqueLetters();
  const visitor = await visitorPage(browser, "unused");
  await visitor.goto("/chat");
  await visitor
    .getByRole("group", { name: "Language" })
    .getByRole("button", { name: "తెలుగు" })
    .click();
  await expect(visitor.getByText(/నమస్కారం!/)).toBeVisible();

  const box = visitor.getByLabel("మీ సందేశం");
  await box.fill(`I am Ravi ${lastName}, ఫోన్ ౯౮౪౮౦ ౧౨౩౪౫`);
  await visitor.getByRole("button", { name: "పంపండి" }).click();
  await expect(visitor.getByRole("status")).toContainText(
    "మా బృందానికి పంపబడ్డాయి",
  );

  const manager = await managerFindsLead(browser, "te", lastName);
  await expect(field(manager, "Call in")).toHaveText("Telugu");
  await expect(field(manager, "Phone")).toHaveText("98480 12345");
});

test("a card number in Hindi digits is refused with a sentence, nothing is saved", async ({
  browser,
}) => {
  const visitor = await visitorPage(browser, "unused");
  await visitor.goto("/chat");
  await visitor.getByRole("button", { name: "हिन्दी" }).click();
  await visitor
    .getByLabel("आपका संदेश")
    .fill("मेरा कार्ड ४१११ ११११ ११११ ११११ है");
  await visitor.getByRole("button", { name: "भेजें" }).click();
  // (Next.js also has its own role="alert" route announcer, so find the sentence by its words.)
  await expect(visitor.getByText(/card numbers/i)).toBeVisible();
  await expect(visitor.getByRole("status")).toHaveCount(0);
});
