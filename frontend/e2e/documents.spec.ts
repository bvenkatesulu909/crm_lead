import { readFile } from "node:fs/promises";

import { expect, test, type Browser, type Page } from "@playwright/test";

import { USERS, login, requireCredentials, uniqueName } from "./helpers";

/**
 * Phase 10: documents on customer accounts, with versions, shared with the customer portal.
 * alpha.agent1 owns "Example Customer One Ltd" (A1); alpha.customer1 is linked to it.
 * Creates clearly fictional "E2E…" files and deletes them again at the end.
 */
test.beforeEach(() => requireCredentials());

const A1 = "ac000000-0000-4000-8000-0000000000a1";

async function signedIn(browser: Browser, user: string, target = "/") {
  const page = await (await browser.newContext()).newPage();
  await login(page, user, target);
  return page;
}

const documents = (page: Page) => page.getByRole("region", { name: "Documents" });

async function uploadFile(page: Page, name: string, body: string, share = false) {
  await documents(page).getByRole("button", { name: "Upload" }).click();
  const dialog = page.getByRole("dialog", { name: "Upload a document" });
  await dialog.getByLabel("File").setInputFiles({ name, mimeType: "application/pdf", buffer: Buffer.from(body) });
  if (share) await dialog.getByLabel("Visible to the customer in the portal").check();
  await dialog.getByRole("button", { name: "Upload" }).click();
} // prettier-ignore

async function download(page: Page, link: ReturnType<Page["getByRole"]>) {
  const [file] = await Promise.all([page.waitForEvent("download"), link.click()]);
  return { name: file.suggestedFilename(), text: (await readFile(await file.path())).toString() };
}

test("documents are uploaded, versioned, shared with the customer and deleted", async ({
  browser,
}) => {
  test.setTimeout(150_000);
  const name = `${uniqueName("E2E-terms-")}.pdf`;

  // 1. The agent uploads a file to their customer and shares it with the customer.
  const agent = await signedIn(browser, USERS.agent1, `/accounts/${A1}`);
  await uploadFile(agent, name, "%PDF-1.7 version one", true);
  await expect(agent.getByRole("status")).toHaveText("The document was uploaded.");
  const link = documents(agent).getByRole("link", { name });
  await expect(link).toBeVisible();
  await expect(documents(agent)).toContainText("Visible to the customer");

  // 2. Wrong file types are refused with a clear message.
  await documents(agent).getByRole("button", { name: "Upload" }).click();
  const dialog = agent.getByRole("dialog", { name: "Upload a document" });
  await dialog.getByLabel("File").setInputFiles({ name: "tool.exe", mimeType: "application/octet-stream", buffer: Buffer.from("MZ\u0090\u0000") });
  await dialog.getByRole("button", { name: "Upload" }).click();
  await expect(dialog.getByText(/file type isn't allowed/)).toBeVisible();
  await dialog.getByRole("button", { name: "Cancel" }).click();

  // 3. Same name again = version 2 (shared again); version 1 stays available to staff.
  await uploadFile(agent, name, "%PDF-1.7 version two", true);
  await expect(agent.getByRole("status")).toHaveText("The document was uploaded.");
  await expect(documents(agent)).toContainText("Version 2");
  expect((await download(agent, documents(agent).getByRole("link", { name }))).text).toBe("%PDF-1.7 version two");
  await documents(agent).getByText("Older versions (1)").click();
  expect((await download(agent, documents(agent).getByRole("link", { name: "Version 1" }))).text).toBe("%PDF-1.7 version one");

  // 4. The customer sees and downloads the newest version in the portal.
  const customer = await signedIn(browser, USERS.customer, `/portal/accounts/${A1}`);
  const shared = customer.getByRole("region", { name: "Documents" });
  const file = await download(customer, shared.getByRole("link", { name }));
  expect(file).toEqual({ name, text: "%PDF-1.7 version two" });

  // 5. Agents can't delete; a manager deletes it (all versions), and the customer loses it.
  await expect(documents(agent).getByRole("button", { name: "Delete" })).toHaveCount(0);
  const manager = await signedIn(browser, USERS.manager, `/accounts/${A1}`);
  const row = documents(manager).getByRole("listitem").filter({ hasText: name });
  await row.getByRole("button", { name: "Delete" }).click();
  await manager.getByRole("dialog", { name: `Delete ${name}?` }).getByRole("button", { name: "Delete" }).click();
  await expect(manager.getByRole("status")).toHaveText("The document was deleted.");
  await expect(documents(manager).getByRole("link", { name })).toHaveCount(0);
  await customer.reload();
  await expect(customer.getByRole("region", { name: "Documents" }).getByRole("link", { name })).toHaveCount(0);
}); // prettier-ignore

test("documents of someone else's customer can't be listed or downloaded", async ({ browser }) => {
  const other = await signedIn(browser, USERS.agent2, `/accounts/${A1}`);
  await expect(other.getByRole("heading", { name: "Page not found" })).toBeVisible();
  const response = await other.request.get(`/documents/${crypto.randomUUID()}/download`, { maxRedirects: 0 });
  expect(response.headers()["content-type"] ?? "").not.toContain("application/pdf");
}); // prettier-ignore
