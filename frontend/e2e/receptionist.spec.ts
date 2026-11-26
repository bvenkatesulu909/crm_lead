import { execFileSync } from "node:child_process";
import path from "node:path";

import { expect, test, type Page } from "@playwright/test";

import { USERS, login, requireCredentials } from "./helpers";

/**
 * The voice receptionist (ADR 0038), end to end: a website visitor reads the notice, presses Start
 * and talks; what was heard and the answer are shown as text; their details become a lead that
 * the sales managers hear about; staff read the conversation on the lead page.
 *
 * Real browser, real Next.js app and route handler, real API, real database and Keycloak. Two
 * stand-ins, both for things that cannot be done in a test: the MICROPHONE (a fake recorder
 * that "records" the sentence the test queues, so the test decides what the visitor says) and
 * the SPEECH SERVICE (the API's `fake` provider, which reads the recorded bytes as text).
 *
 * Needs, besides the chat setup of public-chat.spec.ts (CRM_PUBLIC_CHAT_TENANT_SLUG=alpha-demo,
 * CRM_PUBLIC_CHAT_PROVIDER=fake, the same server key on both sides): CRM_VOICE_PROVIDER=fake in
 * backend/.env and PUBLIC_CHAT_VOICE=on in frontend/.env.local. The "Voice receptionist" agent is
 * switched on and off again by the journey itself (it starts off).
 */
test.beforeEach(() => {
  requireCredentials();
  test.skip(
    !process.env.PUBLIC_CHAT_SERVER_KEY ||
      process.env.PUBLIC_CHAT_VOICE !== "on",
    "PUBLIC_CHAT_SERVER_KEY or PUBLIC_CHAT_VOICE=on is not set in .env.local",
  );
});

function runWorkerOnce() {
  execFileSync(path.join("..", "backend", ".venv", "Scripts", "python.exe"), ["-m", "app.worker", "--once"], {
    cwd: path.join("..", "backend"), timeout: 60_000, stdio: "ignore",
  });
} // prettier-ignore

/** Letters only: the fake chat model reads names made of letters. */
function uniqueLetters() {
  return Date.now()
    .toString(36)
    .replace(/\d/g, (d) => "abcdefghij"[Number(d)]);
}

/**
 * A stand-in microphone, installed before the page loads. `getUserMedia` answers at once; the
 * recorder "records" the next sentence of `window.__say` (its bytes are the words); the sound
 * level is loud for about 0.7 s and then silent, so the page's own silence detection ends the turn.
 */
const FAKE_MICROPHONE = () => {
  const w = window as unknown as {
    __say: string[];
    __recorderStarts: number;
    __microphoneOpened: number;
  };
  w.__say = [];
  w.__recorderStarts = 0;
  w.__microphoneOpened = 0;
  Object.defineProperty(navigator, "mediaDevices", {
    configurable: true,
    value: {
      getUserMedia: async () => {
        w.__microphoneOpened += 1;
        return { getTracks: () => [{ stop() {} }] };
      },
    },
  });
  class FakeRecorder {
    static isTypeSupported() {
      return true;
    }
    state = "inactive";
    mimeType = "audio/webm";
    ondataavailable: ((event: { data: Blob }) => void) | null = null;
    onstop: (() => void) | null = null;
    start() {
      w.__recorderStarts += 1;
      this.state = "recording";
    }
    stop() {
      this.state = "inactive";
      const words = w.__say.shift() ?? "Hello";
      this.ondataavailable?.({
        data: new Blob([words], { type: "audio/webm" }),
      });
      this.onstop?.();
    }
  }
  class FakeAudioContext {
    createAnalyser() {
      let calls = 0;
      return {
        fftSize: 1024,
        getByteTimeDomainData(samples: Uint8Array) {
          calls += 1;
          // About the first 0.7 s (7 looks, 100 ms apart): speech; then silence.
          samples.fill(calls <= 7 ? 200 : 128);
        },
      };
    }
    createMediaStreamSource() {
      return { connect() {} };
    }
    close() {
      return Promise.resolve();
    }
  }
  Object.assign(window, {
    MediaRecorder: FakeRecorder,
    AudioContext: FakeAudioContext,
  });
};

async function say(page: Page, ...sentences: string[]) {
  await page.evaluate((s) => {
    (window as unknown as { __say: string[] }).__say.push(...s);
  }, sentences);
}

const counter = (page: Page, name: "__recorderStarts" | "__microphoneOpened") =>
  page.evaluate((n) => (window as unknown as Record<string, number>)[n], name);

async function switchReceptionist(page: Page, on: boolean) {
  await page.goto("/automation/agents");
  const box = page.getByRole("article", { name: "Voice receptionist" });
  const switchedOn = box.getByLabel("Switched on");
  if ((await switchedOn.isChecked()) !== on) {
    if (on) await switchedOn.check();
    else await switchedOn.uncheck();
    await box.getByRole("button", { name: "Save settings" }).click();
    await expect(page.getByText(/were saved/)).toBeVisible();
  }
}

test("a visitor talks to the receptionist and leaves their details", async ({
  browser,
}) => {
  test.setTimeout(240_000);
  const lastName = "Voice" + uniqueLetters();
  const fullName = `Ravi ${lastName}`;
  const details = `I am ${fullName}, phone 98480 12345`;

  const admin = await (await browser.newContext()).newPage();
  await login(admin, USERS.admin);
  try {
    // 1. Off until an administrator switches it on: the call ends at once, in words, and the
    // typed chat stays available. (A different visitor address each run, as in the chat journey.)
    await switchReceptionist(admin, false);
    const address = `198.51.100.${1 + Math.floor(Math.random() * 254)}`;
    const context = await browser.newContext({
      extraHTTPHeaders: { "x-forwarded-for": address },
    });
    await context.addInitScript(FAKE_MICROPHONE);
    const visitor = await context.newPage();
    await visitor.goto("/chat");
    await visitor.getByRole("button", { name: "Talk to us" }).click();
    await say(visitor, "Hello, are you there?");
    await visitor
      .getByRole("button", { name: "I understand - start the call" })
      .click();
    await expect(
      visitor.getByText(/Something went wrong with the call/),
    ).toBeVisible();
    await expect(
      visitor.getByRole("button", { name: "Talk to us" }),
    ).toHaveCount(0);
    await expect(visitor.getByLabel("Your message")).toBeVisible(); // typing still works

    // 2. An administrator switches the receptionist on.
    await switchReceptionist(admin, true);

    // 3. The notice comes first: nothing is recorded, not even the microphone is opened, until
    // the visitor presses Start.
    await visitor.reload();
    await visitor.getByRole("button", { name: "Talk to us" }).click();
    await expect(
      visitor.getByText(/automated assistant, not a person/),
    ).toBeVisible();
    await expect(
      visitor.getByText(/do not keep your voice recording/),
    ).toBeVisible();
    expect(await counter(visitor, "__microphoneOpened")).toBe(0);
    expect(await counter(visitor, "__recorderStarts")).toBe(0);

    // 4. Start: the receptionist says what it is, the visitor speaks, and what was heard and the
    // answer appear as text.
    await say(visitor, "Hi, I want a 3BHK flat", details);
    await visitor
      .getByRole("button", { name: "I understand - start the call" })
      .click();
    const conversation = visitor.getByRole("list", { name: "Conversation" });
    await expect(conversation).toContainText("I am an automated assistant");
    await expect(conversation).toContainText("Hi, I want a 3BHK flat");
    await expect(conversation).toContainText(/your name and phone number\?/i);

    // 5. The second turn gives the details: they are saved, and the page says so.
    await expect(conversation).toContainText(details);
    await expect(visitor.getByRole("status").first()).toContainText(
      "passed on to our team",
      { timeout: 60_000 },
    );
    // The visitor ends the call whenever they like.
    await visitor.getByRole("button", { name: "End the call" }).click();
    await expect(visitor.getByText("The call has ended.")).toBeVisible();
    // The conversation token is an httpOnly cookie: page JavaScript can't read it.
    expect(await visitor.evaluate(() => document.cookie)).not.toContain(
      "crm_chat",
    );

    // 6. The worker turns the event into notifications; a sales manager opens the lead and reads
    // the conversation, with the words that were heard.
    runWorkerOnce();
    const manager = await (await browser.newContext()).newPage();
    await login(manager, USERS.manager, "/notifications");
    const note = manager.getByRole("button", {
      name: new RegExp(`New lead from the website chat: ${fullName}`),
    });
    await expect(note).toBeVisible();
    await note.click();
    await expect(manager.getByRole("heading", { level: 1 })).toHaveText(
      fullName,
    );
    const chat = manager.getByRole("region", { name: "Website chat" });
    await expect(chat).toContainText("Hi, I want a 3BHK flat");
    await expect(chat).toContainText(details);

    // 7. An agent may not see the unassigned lead, nor the conversation.
    const leadUrl = manager.url();
    const agent = await (await browser.newContext()).newPage();
    await login(agent, USERS.agent1, "/");
    await agent.goto(leadUrl);
    await expect(
      agent.getByText(/not found|doesn't exist/i).first(),
    ).toBeVisible();
  } finally {
    await switchReceptionist(admin, false); // as it was found: off
  }
});

test("without the visitor's press on Start the voice endpoint refuses and records nothing", async ({
  request,
  browser,
}) => {
  test.setTimeout(120_000);
  const admin = await (await browser.newContext()).newPage();
  await login(admin, USERS.admin);
  try {
    await switchReceptionist(admin, true);
    // The route handler is ours, so the browser's own request shows what a bot would see: no
    // consent version, no turn.
    const response = await request.post("/api/public-chat/voice", {
      multipart: {
        audio: {
          name: "turn.webm",
          mimeType: "audio/webm",
          buffer: Buffer.from("Hello"),
        },
        language: "en",
      },
    });
    expect(response.status()).toBe(422);
    expect((await response.json()).code).toBe("voice_consent_required");
    // Audio that is not audio is refused before it leaves the web server.
    const wrongType = await request.post("/api/public-chat/voice", {
      multipart: {
        audio: {
          name: "x.html",
          mimeType: "text/html",
          buffer: Buffer.from("<b>hi</b>"),
        },
        consent_version: "1",
      },
    });
    expect(wrongType.status()).toBe(422);
    expect((await wrongType.json()).code).toBe("invalid");
  } finally {
    await switchReceptionist(admin, false);
  }
});
