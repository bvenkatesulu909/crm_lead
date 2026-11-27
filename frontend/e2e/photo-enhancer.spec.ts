import { expect, test, type Browser, type Page } from "@playwright/test";

import { USERS, login, requireCredentials, uniqueName } from "./helpers";

/**
 * Property photo enhancer (ADR 0039), end to end: an administrator switches it on, an agent
 * uploads a (tiny, fictional) photo to their own customer, adjusts it, the worker makes the copy,
 * the copy is badged "Enhanced" and the original is kept; a colleague cannot reach the photo.
 *
 * Needs the API, the WORKER (python -m app.worker) and the file store running. The photo is a
 * plain 96 x 72 picture made for this test; the copy and the upload are deleted again at the end.
 */
test.beforeEach(() => requireCredentials());

const A1 = "ac000000-0000-4000-8000-0000000000a1";
const PNG = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAGAAAABICAIAAACGBWc0AAAAc0lEQVR42u3QIQEAMAgAsPNwaDT9g5AAj9giLLL6sfsKBAkSJEiQIEGCECRIkCBBggQJQpAgQYIECRIkCEGCBAkSJEiQIEEIEiRIkCBBggQhSJAgQYIECRKEIEGCBAkSJEiQIAQJEiRIkCBBghAkSJCgKwZk4QGAGUdb3wAAAABJRU5ErkJggg==",
  "base64",
);

async function signedIn(browser: Browser, user: string, target = "/") {
  const page = await (await browser.newContext()).newPage();
  await login(page, user, target);
  return page;
}

const card = (page: Page, title: string) =>
  page.getByRole("article", { name: title });

async function setSwitch(admin: Page, on: boolean) {
  await admin.goto("/automation/agents");
  const box = card(admin, "Property photo enhancer");
  const toggle = box.getByLabel("Switched on");
  if ((await toggle.isChecked()) !== on) {
    if (on) await toggle.check();
    else await toggle.uncheck();
    await box.getByRole("button", { name: "Save settings" }).click();
    await expect(admin.getByText(/were saved/)).toBeVisible();
  }
}

test("an agent adjusts a photo: preview, copy, badge, original kept; a colleague cannot reach it", async ({
  browser,
}) => {
  test.setTimeout(180_000);
  const name = `${uniqueName("E2E-living-")}.png`;
  const admin = await signedIn(browser, USERS.admin);
  await setSwitch(admin, true);
  try {
    // 1. The agent uploads a photo to their customer and finds "Adjust photo" next to it.
    const agent = await signedIn(browser, USERS.agent1, `/accounts/${A1}`);
    const documents = agent.getByRole("region", { name: "Documents" });
    await documents.getByRole("button", { name: "Upload" }).click();
    const upload = agent.getByRole("dialog", { name: "Upload a document" });
    await upload
      .getByLabel("File")
      .setInputFiles({ name, mimeType: "image/png", buffer: PNG });
    await upload.getByRole("button", { name: "Upload" }).click();
    await expect(documents.getByRole("link", { name })).toBeVisible();
    await documents.getByRole("link", { name: "Adjust photo" }).first().click();
    await expect(
      agent.getByRole("heading", { name: "Adjust a photo" }),
    ).toBeVisible();
    const photoUrl = agent.url();

    // 2. The warning is always there, and the server makes a preview.
    await expect(agent.getByTestId("people-warning")).toContainText(
      "people and number plates",
    );
    await expect(agent.getByAltText(/Preview of/)).toBeVisible({
      timeout: 30_000,
    });

    // 3. Ask for the real copy: it is made in the background and appears badged "Enhanced".
    await agent.getByLabel("Even out the exposure").check();
    await agent.getByRole("button", { name: "Make enhanced copy" }).click();
    await expect(agent.getByText(/is being made/)).toBeVisible();
    const copies = agent.getByTestId("photo-copies");
    await expect(copies.getByText("Enhanced", { exact: true })).toBeVisible({
      timeout: 60_000,
    });
    await expect(copies).toContainText("Exposure evened out");
    await copies.getByText("Show original").click();
    await expect(copies.getByAltText("Original photo")).toBeVisible();
    await expect(copies.getByAltText("Enhanced copy")).toBeVisible();

    // 4. A colleague who does not own the customer cannot reach the photo.
    const colleague = await signedIn(browser, USERS.agent2, photoUrl);
    await expect(colleague.getByText(/not found|doesn't exist/i)).toBeVisible();

    // 5. Deleting the copy keeps the original photo.
    await copies.getByRole("button", { name: "Delete copy" }).click();
    await agent
      .getByRole("dialog", { name: "Delete this adjusted copy?" })
      .getByRole("button", { name: "Delete" })
      .click();
    await expect(agent.getByText(/original photo is untouched/i)).toBeVisible();
    await expect(agent.getByText(/No adjusted copies yet/)).toBeVisible();
    await agent.goto(`/accounts/${A1}`);
    await expect(documents.getByRole("link", { name })).toBeVisible();

    // 6. Tidy up: delete the uploaded photo.
    const row = documents.getByRole("listitem").filter({ hasText: name });
    await row.getByRole("button", { name: "Delete" }).click();
    await agent
      .getByRole("dialog")
      .getByRole("button", { name: "Delete" })
      .click();
    await expect(documents.getByRole("link", { name })).toHaveCount(0);
  } finally {
    await setSwitch(admin, false);
  }
});
