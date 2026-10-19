import { expect, type Page } from "@playwright/test";

/**
 * Reads e-mails caught by Mailpit (http://localhost:8025), the local inbox for everything
 * Keycloak sends. Nothing reaches a real mailbox.
 */
const MAILPIT = "http://localhost:8025/api/v1";

type Summary = { ID: string; Subject: string };

/** Waits for the newest e-mail to `address` and returns the first Keycloak action link in it. */
export async function linkFromLatestEmail(address: string): Promise<string> {
  let link = "";
  await expect
    .poll(
      async () => {
        const search = await fetch(
          `${MAILPIT}/search?query=${encodeURIComponent(`to:${address}`)}`,
        ).then((r) => r.json() as Promise<{ messages: Summary[] }>);
        const latest = search.messages[0];
        if (!latest) return "";
        const message = await fetch(`${MAILPIT}/message/${latest.ID}`).then(
          (r) => r.json() as Promise<{ Text: string }>,
        );
        link =
          /https?:\/\/\S+login-actions\/action-token\S+/.exec(
            message.Text,
          )?.[0] ?? "";
        return link;
      },
      { timeout: 20_000, message: `e-mail to ${address}` },
    )
    .not.toBe("");
  return link;
}

/** A fictional, strong password for a test person (never a real one). */
export const testPassword = () =>
  `E2e-${crypto.randomUUID().replaceAll("-", "").slice(0, 16)}!`;

/**
 * Follows a set-your-password link: Keycloak may first ask to confirm the e-mail, then shows
 * the "Update password" form. Ends wherever Keycloak sends the browser afterwards.
 */
export async function setPasswordFromEmail(
  page: Page,
  link: string,
  password: string,
) {
  await page.goto(link);
  const proceed = page.getByRole("link", { name: /proceed/i });
  if (await proceed.isVisible().catch(() => false)) await proceed.click();
  await page.locator("#password-new").fill(password);
  await page.locator("#password-confirm").fill(password);
  await page.locator("input[type=submit], button[type=submit]").first().click();
}

export type MailMessage = {
  Subject: string;
  Text: string;
  ReplyTo: { Address: string }[];
  Attachments: { FileName: string; ContentType: string }[];
};

/** Waits for the newest e-mail to `address` (any sender) and returns it. */
export async function latestMessageTo(address: string): Promise<MailMessage> {
  let found: MailMessage | null = null;
  await expect
    .poll(
      async () => {
        const search = await fetch(
          `${MAILPIT}/search?query=${encodeURIComponent(`to:${address}`)}`,
        ).then((r) => r.json() as Promise<{ messages: Summary[] }>);
        const latest = search.messages[0];
        if (!latest) return false;
        found = await fetch(`${MAILPIT}/message/${latest.ID}`).then(
          (r) => r.json() as Promise<MailMessage>,
        );
        return true;
      },
      { timeout: 20_000, message: `e-mail to ${address}` },
    )
    .toBe(true);
  return found as unknown as MailMessage;
}
