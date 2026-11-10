import { stat } from "node:fs/promises";

import { expect, test, type Browser, type Page } from "@playwright/test";

import { USERS, login, requireCredentials, uniqueName } from "./helpers";

/**
 * ADR 0025 step DU4: files go from the browser straight to the file store through a signed
 * link, so a file larger than the web host's 6 MB request limit (Netlify) can be uploaded.
 * The proof: a 15 MB document is uploaded and downloaded again, and NO request to the web app
 * itself carries more than 1 MB. Creates clearly fictional "E2E…" files and deletes them.
 *
 * Needs the file store (SeaweedFS) with its CORS rule for http://localhost:3000, and the API
 * at DU2 or later (migrations 0054/0055).
 */
test.beforeEach(() => requireCredentials());

const A1 = "ac000000-0000-4000-8000-0000000000a1";
const WEB = "http://localhost:3000";
const FIFTEEN_MB = 15 * 1024 * 1024;

async function signedIn(browser: Browser, user: string, target: string) {
  const page = await (await browser.newContext()).newPage();
  await login(page, user, target);
  return page;
}

/**
 * Which origins received a POST, and whether any of them carried a file form (multipart).
 * Playwright does not expose a file upload's body, so the content type is what tells us.
 */
function watchPosts(page: Page) {
  const web: string[] = [];
  const store: string[] = [];
  page.on("request", (request) => {
    if (request.method() !== "POST") return;
    const type = request.headers()["content-type"] ?? "";
    if (request.url().startsWith(WEB)) web.push(type);
    else store.push(new URL(request.url()).origin);
  });
  return { web, store };
}

/** A fictional PDF: a valid header, then padding up to the wanted size. */
function bigPdf(size: number) {
  const head = Buffer.from("%PDF-1.7\n% E2E fictional test file\n");
  return Buffer.concat([head, Buffer.alloc(size - head.length, 0x20)]);
}

test("a 15 MB document goes straight to the file store and comes back intact", async ({
  browser,
}) => {
  test.setTimeout(240_000);
  const name = `${uniqueName("E2E-big-")}.pdf`;
  const agent = await signedIn(browser, USERS.agent1, `/accounts/${A1}`);
  const posts = watchPosts(agent);
  const documents = agent.getByRole("region", { name: "Documents" });

  await documents.getByRole("button", { name: "Upload" }).click();
  const dialog = agent.getByRole("dialog", { name: "Upload a document" });
  await dialog.getByLabel("File").setInputFiles({ name, mimeType: "application/pdf", buffer: bigPdf(FIFTEEN_MB) });
  await dialog.getByRole("button", { name: "Upload" }).click();
  await expect(agent.getByRole("status")).toHaveText("The document was uploaded.", { timeout: 120_000 });
  const link = documents.getByRole("link", { name });
  await expect(link).toBeVisible();
  await expect(documents).toContainText("15.0 MB");

  // The file went to the store once, and never through the web app.
  expect(posts.store).toHaveLength(1);
  expect(posts.store[0]).not.toBe(WEB);
  expect(posts.web.filter((type) => type.includes("multipart"))).toEqual([]);

  // Download: a redirect to a short-lived link, the same size and name back.
  const [file] = await Promise.all([agent.waitForEvent("download"), link.click()]);
  expect(file.suggestedFilename()).toBe(name);
  expect((await stat(await file.path())).size).toBe(FIFTEEN_MB);

  // A file whose content does not match its name is refused after it reached the store.
  await documents.getByRole("button", { name: "Upload" }).click();
  await dialog.getByLabel("File").setInputFiles({ name: "E2E-fake.pdf", mimeType: "application/pdf", buffer: Buffer.from("MZ\u0090\u0000 not a pdf") });
  await dialog.getByRole("button", { name: "Upload" }).click();
  await expect(dialog.getByRole("alert")).toBeVisible();
  await dialog.getByRole("button", { name: "Cancel" }).click();
  await expect(documents.getByRole("link", { name: "E2E-fake.pdf" })).toHaveCount(0);

  // Clean up as a manager (agents can't delete): this run's file and any left by a failed run.
  const manager = await signedIn(browser, USERS.manager, `/accounts/${A1}`);
  const leftovers = manager.getByRole("region", { name: "Documents" }).getByRole("listitem").filter({ hasText: /E2E-big-/ });
  for (let left = await leftovers.count(); left > 0; left--) {
    const row = leftovers.first();
    const file = (await row.getByRole("link").first().textContent()) ?? "";
    await row.getByRole("button", { name: "Delete" }).click();
    await manager.getByRole("dialog", { name: `Delete ${file}?` }).getByRole("button", { name: "Delete" }).click();
    await expect(manager.getByRole("status")).toHaveText("The document was deleted.");
    await expect(leftovers).toHaveCount(left - 1); // wait for the list before the next one
  }
  await expect(manager.getByRole("link", { name })).toHaveCount(0);
}); // prettier-ignore

test("a knowledge document is uploaded through the store as well", async ({ browser }) => {
  const title = uniqueName("E2E knowledge ");
  const admin = await signedIn(browser, USERS.admin, "/knowledge");
  const posts = watchPosts(admin);
  await admin.getByLabel(/Title/).fill(title);
  await admin.getByLabel("File").setInputFiles({ name: "e2e-returns.txt", mimeType: "text/plain", buffer: Buffer.from(`# ${title}\n\nFictional returns policy: 14 days.\n`) });
  await admin.getByRole("button", { name: "Upload for indexing" }).click();
  await expect(admin.getByText(/Uploaded\. The status below becomes/)).toBeVisible();
  await expect(admin.getByText(title, { exact: true })).toBeVisible();
  expect(posts.store).toHaveLength(1);
  expect(posts.web.filter((type) => type.includes("multipart"))).toEqual([]);

  // Clean up this run's document and any left by a failed run.
  const leftovers = admin.getByRole("row").filter({ hasText: /E2E knowledge / });
  for (let left = await leftovers.count(); left > 0; left--) {
    const row = leftovers.first();
    const named = (await row.locator("p").first().textContent()) ?? "";
    await row.getByRole("button", { name: "Delete" }).click();
    await admin.getByRole("dialog", { name: `Delete ${named}?` }).getByRole("button", { name: "Delete" }).click();
    await expect(admin.getByText("Deleted the document, its chunks and the stored file.")).toBeVisible();
    await expect(leftovers).toHaveCount(left - 1); // wait for the list before the next one
  }
}); // prettier-ignore
