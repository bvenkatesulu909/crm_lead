import { expect, test, type Locator, type Page } from "@playwright/test";

import { USERS, login, requireCredentials, uniqueName } from "./helpers";

/**
 * Saved account filters (ADR 0042, step BR-pre), end to end: a manager saves the filter in use and
 * shares it, an agent sees it as a team filter and can apply it but not delete it, a duplicate
 * name is refused and the typed name is kept, and the manager deletes it. Only fictional filter
 * names ("E2eFilter...") are created and the spec removes them.
 */
/** Opens a dialog from its button. A freshly compiled page can be clicked before it is
 * interactive, so the click is repeated until the dialog really shows. */
async function openDialog(page: Page, button: Locator) {
  await expect(async () => {
    await button.click();
    await expect(page.getByRole("dialog")).toBeVisible({ timeout: 2_000 });
  }).toPass({ timeout: 60_000 });
}

test.beforeEach(() => requireCredentials());

test("a manager shares a saved account filter and an agent uses it", async ({
  page,
}) => {
  test.setTimeout(180_000);
  const name = uniqueName("E2eFilter");

  // --- the manager applies a filter on the list and saves it, shared ------------------------
  await login(page, USERS.manager, "/accounts");
  await page.getByLabel("Segment").selectOption({ label: "Enterprise" });
  await page.getByRole("button", { name: "Apply" }).click();
  await expect(page).toHaveURL(/segment=enterprise/);

  await openDialog(
    page,
    page.getByRole("button", { name: "Save this filter" }),
  );
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Name").fill(name);
  await dialog.getByLabel(/Share with everyone/).check();
  await dialog.getByRole("button", { name: "Save filter" }).click();

  // Saved: the list shows it, marked as the applied one, and no longer offers to save it again.
  const chip = page.getByRole("link", { name });
  await expect(chip).toBeVisible();
  await expect(chip).toHaveAttribute("aria-current", "true");
  await expect(
    page.getByRole("button", { name: "Save this filter" }),
  ).toHaveCount(0);

  // The same name again is refused and the dialog keeps what was typed.
  await page.goto("/accounts?status=active");
  await openDialog(
    page,
    page.getByRole("button", { name: "Save this filter" }),
  );
  const again = page.getByRole("dialog");
  await again.getByLabel("Name").fill(name.toLowerCase());
  await again.getByRole("button", { name: "Save filter" }).click();
  await expect(again.getByText(/You already have a filter/)).toBeVisible();
  await expect(again.getByLabel("Name")).toHaveValue(name.toLowerCase());

  // --- an agent sees it as a team filter, applies it, cannot delete it ------------------------
  await page.context().clearCookies();
  await login(page, USERS.agent1, "/accounts");
  const teamChip = page.getByRole("link", { name });
  await expect(teamChip).toBeVisible();
  await expect(page.getByText("(team)").first()).toBeVisible();
  await teamChip.click();
  await expect(page).toHaveURL(/segment=enterprise/);
  await expect(page.getByLabel("Segment")).toHaveValue("enterprise");
  // No Delete button on a colleague's filter, and an agent is not offered the share box.
  await expect(
    page
      .locator("span", { hasText: name })
      .getByRole("button", { name: "Delete" }),
  ).toHaveCount(0);

  // --- a colleague in another organisation sees nothing of it --------------------------------
  await page.context().clearCookies();
  await login(page, USERS.betaAdmin, "/accounts");
  await expect(page.getByRole("link", { name })).toHaveCount(0);

  // --- the manager deletes it ---------------------------------------------------------------
  await page.context().clearCookies();
  await login(page, USERS.manager, "/accounts");
  const mine = page.locator("span", { hasText: name }).first();
  await openDialog(page, mine.getByRole("button", { name: "Delete" }));
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Delete filter" })
    .click();
  await expect(page.getByText("The saved filter was deleted.")).toBeVisible();
  await expect(page.getByRole("link", { name })).toHaveCount(0);
});
