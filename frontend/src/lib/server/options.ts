import "server-only";

import type {
  Account,
  AccountPage,
  ContactPage,
  DirectoryUser,
  OpportunityPage,
  Price,
  PriceBook,
  QuoteSettings,
} from "@/lib/api-types";
import { DEFAULT_APPROVAL_LIMIT } from "@/lib/quotes";
import { apiFetch } from "@/lib/server/api";

/**
 * Choices for account/contact forms. Both lists come from the API, so they contain only what
 * this user may see (agents: their own accounts) - the API checks every choice again on save.
 */
export async function accountOptions(
  exceptId?: string,
): Promise<{ id: string; name: string }[]> {
  const page = await apiFetch<AccountPage>("/accounts?limit=200");
  return page.items
    .filter((a) => a.id !== exceptId)
    .map((a) => ({ id: a.id, name: a.name }));
}

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/**
 * One account as a choice, for forms opened from an account page (?account=<id>) where the
 * account picker should start with that account. The API decides whether this user may see
 * it; if not (or the id is not an id), the form simply starts without a chosen account.
 */
export async function accountOption(
  id: string | string[] | undefined,
): Promise<{ id: string; name: string } | null> {
  if (typeof id !== "string" || !UUID.test(id)) return null;
  try {
    const account = await apiFetch<Account>(`/accounts/${id}`);
    return { id: account.id, name: account.name };
  } catch {
    return null;
  }
}

export async function salesOwnerOptions(): Promise<
  { id: string; name: string }[]
> {
  const people = await apiFetch<DirectoryUser[]>("/users?assignable=true");
  return people.map((p) => ({ id: p.id, name: p.display_name }));
}

/** Contacts the user may see, with their account (for "primary contact" choices). */
export async function contactOptions(): Promise<
  { id: string; name: string; accountId: string | null }[]
> {
  const page = await apiFetch<ContactPage>("/contacts?limit=200");
  return page.items.map((c) => ({
    id: c.id,
    name: [c.first_name, c.last_name].filter(Boolean).join(" "),
    accountId: c.account_id,
  }));
}

/** Active price books with their prices (for the quote form). */
export async function priceBookOptions(): Promise<{
  books: PriceBook[];
  prices: Record<string, Price[]>;
}> {
  const books = await apiFetch<PriceBook[]>("/price-books?active=true");
  const lists = await Promise.all(
    books.map((b) => apiFetch<Price[]>(`/price-books/${b.id}/prices`)),
  );
  return {
    books,
    prices: Object.fromEntries(books.map((b, i) => [b.id, lists[i]])),
  };
}

/** Open deals the user may see, with their account (for linking quotes). */
export async function dealOptions(): Promise<
  { id: string; name: string; accountId: string }[]
> {
  const page = await apiFetch<OpportunityPage>(
    "/opportunities?limit=200&stage=prospecting&stage=qualification&stage=proposal&stage=negotiation",
  );
  return page.items.map((o) => ({
    id: o.id,
    name: o.name,
    accountId: o.account_id,
  }));
}

/** The organisation's approval limit for quote discounts (falls back to the default). */
export async function approvalLimitOption(): Promise<number> {
  return apiFetch<QuoteSettings>("/quotes/settings")
    .then((s) => Number(s.approval_limit_percent))
    .catch(() => DEFAULT_APPROVAL_LIMIT);
}
