import { createHmac } from "node:crypto";
import { execFileSync } from "node:child_process";
import path from "node:path";

import { expect, test, type Browser, type Page } from "@playwright/test";

import { USERS, chooseAccount, login, requireCredentials } from "./helpers";

/**
 * UPI payment links (ADR 0031), end to end with the SCRIPTED provider: a manager makes an invoice
 * in rupees, an administrator switches the feature on, the manager creates a payment link, the
 * customer sees a "Pay by UPI" button, a signed webhook arrives (signed here with the same HMAC
 * Razorpay uses), the worker records the payment and the invoice is paid. A forged webhook changes
 * nothing, and an agent who may not collect payments gets no button. Creates fictional invoices and
 * puts the switch back.
 *
 * Needs the API and the worker started with CRM_RAZORPAY_MODE=fake and CRM_RAZORPAY_WEBHOOK_SECRET
 * set, the same secret in E2E_RAZORPAY_WEBHOOK_SECRET here, and no standing worker; without it the
 * spec is skipped.
 */
const SECRET = process.env.E2E_RAZORPAY_WEBHOOK_SECRET;
// Fresh ids every run: an event id and a payment id can each be recorded only once.
const RUN = Date.now().toString(36);
const API = process.env.E2E_API_URL ?? "http://127.0.0.1:8000";

test.beforeEach(() => {
  requireCredentials();
  test.skip(
    !SECRET,
    "E2E_RAZORPAY_WEBHOOK_SECRET is not set (scripted provider off)",
  );
});

function runWorkerOnce() {
  execFileSync(
    path.join("..", "backend", ".venv", "Scripts", "python.exe"),
    ["-m", "app.worker", "--once"],
    { cwd: path.join("..", "backend"), timeout: 90_000, stdio: "ignore" },
  );
}

async function signedIn(
  browser: Browser,
  user: string,
  target = "/",
): Promise<Page> {
  const page = await (await browser.newContext()).newPage();
  await login(page, user, target);
  return page;
}

/** Switch the registry entry on or off as the administrator; returns whether it was on. */
async function setSwitch(admin: Page, on: boolean): Promise<boolean> {
  await admin.goto("/automation/agents");
  const box = admin.getByRole("article", { name: "UPI payment links" });
  await expect(box).toBeVisible();
  const toggle = box.getByLabel("Switched on");
  const wasOn = await toggle.isChecked();
  if (wasOn !== on) {
    await toggle.setChecked(on);
    await box.getByRole("button", { name: "Save settings" }).click();
    await expect(admin.getByText(/were saved/)).toBeVisible();
  }
  return wasOn;
}

/** A confirmed order in INR for 3 x 19.99 (no tax) = 59.97, then an issued invoice. */
async function issuedInvoice(page: Page): Promise<string> {
  await page.goto("/orders/new");
  await chooseAccount(page, "Customer account", "Example Customer One Ltd");
  await page.getByLabel("Currency").selectOption("INR");
  const line = page.getByRole("group", { name: "Line 1" });
  await line.getByLabel("Description").fill("Widget");
  await line.getByLabel("Quantity").fill("3");
  await line.getByLabel(/Unit price/).fill("19.99");
  await line.getByLabel("Tax rate (%)").fill("0");
  await page.getByRole("button", { name: "Save draft" }).click();
  await page.getByRole("group", { name: "Order actions" }).getByRole("button", { name: "Confirm order" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Confirm order" }).click();
  await expect(page.getByRole("status")).toContainText("The order was confirmed.");
  await page.getByRole("button", { name: "Create invoice" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Create draft invoice" }).click();
  await expect(page.getByRole("status")).toHaveText("The draft invoice was created from the order.");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Draft invoice");
  const actions = page.getByRole("group", { name: "Invoice actions" });
  await actions.getByRole("button", { name: "Issue invoice" }).click();
  await page.getByRole("dialog").filter({ visible: true }).getByRole("button", { name: "Issue invoice" }).click();
  await expect(page.getByRole("status")).toContainText("The invoice was issued.");
  return new URL(page.url()).pathname.split("/").pop() ?? "";
} // prettier-ignore

function signed(body: string, secret: string) {
  return createHmac("sha256", secret).update(body).digest("hex");
}

test("a payment link is created, paid through a signed webhook and recorded", async ({
  browser,
  request,
}) => {
  test.setTimeout(480_000);
  const admin = await signedIn(browser, USERS.admin, "/automation/agents");
  const wasOn = await setSwitch(admin, true);
  try {
    const manager = await signedIn(browser, USERS.manager, "/orders");
    const invoiceId = await issuedInvoice(manager);
    const card = manager.getByRole("region", { name: "Pay by UPI" });

    // 1. No link yet; the manager creates one.
    await expect(card).toContainText("No payment link yet.");
    await card.getByRole("button", { name: "Create UPI payment link" }).click();
    await expect(manager.getByRole("status")).toContainText(
      "The UPI payment link was created.",
    );
    const open = card.getByTestId("open-link");
    await expect(open).toContainText("59.97");
    const address =
      (await open.locator("p.font-mono").textContent())?.trim() ?? "";
    expect(address).toMatch(/^https:\/\//);
    const linkId = address.split("/").pop() ?? "";

    // 2. The customer sees a pay button that points at the same address.
    const customer = await signedIn(
      browser,
      USERS.customer,
      `/portal/invoices/${invoiceId}`,
    );
    const pay = customer.getByRole("link", { name: "Pay by UPI" });
    await expect(pay).toHaveAttribute("href", address);
    await expect(customer.getByRole("note").first()).toContainText(
      "we never see your UPI details",
    );

    // 3. A forged webhook (wrong signature) is refused and changes nothing.
    const body = JSON.stringify({
      event: "payment_link.paid",
      payload: {
        payment_link: { entity: { id: linkId } },
        payment: {
          entity: { id: `pay_e2e_${RUN}`, amount: 5997, currency: "INR" },
        },
      },
    });
    const forged = await request.post(
      `${API}/api/v1/integrations/razorpay/webhook`,
      {
        data: body,
        headers: {
          "content-type": "application/json",
          "x-razorpay-signature": "0".repeat(64),
          "x-razorpay-event-id": `evt_e2e_forged_${RUN}`,
        },
      },
    );
    expect(forged.status()).toBe(401);
    runWorkerOnce();
    await manager.reload();
    await expect(manager.getByText("No payments recorded.")).toBeVisible();

    // 4. The real one is accepted; nothing changes until the worker has run.
    const headers = {
      "content-type": "application/json",
      "x-razorpay-signature": signed(body, SECRET ?? ""),
      "x-razorpay-event-id": `evt_e2e_paid_${RUN}`,
    };
    const accepted = await request.post(
      `${API}/api/v1/integrations/razorpay/webhook`,
      { data: body, headers },
    );
    expect(accepted.status()).toBe(200);
    expect((await accepted.json()).result).toBe("stored");
    await manager.reload();
    await expect(manager.getByText("No payments recorded.")).toBeVisible();
    // The same delivery again is acknowledged and ignored.
    const again = await request.post(
      `${API}/api/v1/integrations/razorpay/webhook`,
      { data: body, headers },
    );
    expect((await again.json()).result).toBe("duplicate");

    // 5. The worker records the payment: the invoice is paid and the link is closed.
    runWorkerOnce();
    await manager.reload();
    await expect(manager.getByText(/UPI · received/)).toBeVisible();
    await expect(manager.getByText(`pay_e2e_${RUN}`)).toBeVisible();
    await expect(
      manager.getByText("Paid", { exact: true }).first(),
    ).toBeVisible();
    await expect(card.getByTestId("open-link")).toHaveCount(0);
    await customer.reload();
    await expect(
      customer.getByRole("link", { name: "Pay by UPI" }),
    ).toHaveCount(0);
  } finally {
    if (!wasOn) await setSwitch(admin, false);
  }
});

test("with the feature off the button explains why, and an agent gets no button", async ({
  browser,
}) => {
  test.setTimeout(300_000);
  const admin = await signedIn(browser, USERS.admin, "/automation/agents");
  const wasOn = await setSwitch(admin, false);
  try {
    const manager = await signedIn(browser, USERS.manager, "/orders");
    const invoiceId = await issuedInvoice(manager);
    const card = manager.getByRole("region", { name: "Pay by UPI" });
    await card.getByRole("button", { name: "Create UPI payment link" }).click();
    await expect(card.getByRole("alert")).toContainText(/switched off/);
    const agent = await signedIn(
      browser,
      USERS.agent1,
      `/invoices/${invoiceId}`,
    );
    await expect(
      agent.getByRole("button", { name: /Create UPI payment link/ }),
    ).toHaveCount(0);
  } finally {
    if (wasOn) await setSwitch(admin, true);
  }
});
