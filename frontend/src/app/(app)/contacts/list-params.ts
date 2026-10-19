import { EMAIL_CONSENTS } from "@/lib/api-types";

export const CONTACT_PAGE_SIZE = 25;

type Raw = Record<string, string | string[] | undefined>;
const one = (v: string | string[] | undefined) =>
  (Array.isArray(v) ? v[0] : v) ?? "";

export type ContactListParams = { q: string; consent: string; page: number };

/** Reads the URL's search parameters; anything invalid falls back to the default. */
export function parseContactParams(raw: Raw): ContactListParams {
  const consent = one(raw.consent);
  const page = Number.parseInt(one(raw.page), 10);
  return {
    q: one(raw.q).trim().slice(0, 100),
    consent: (EMAIL_CONSENTS as readonly string[]).includes(consent)
      ? consent
      : "",
    page: Number.isFinite(page) && page > 0 && page <= 5000 ? page : 1,
  };
}

/** Query string for the backend's GET /contacts. */
export function contactApiQuery(p: ContactListParams): string {
  const query = new URLSearchParams({
    limit: String(CONTACT_PAGE_SIZE),
    offset: String((p.page - 1) * CONTACT_PAGE_SIZE),
  });
  if (p.q) query.set("q", p.q);
  if (p.consent) query.set("email_consent", p.consent);
  return query.toString();
}

export function contactPageHref(p: ContactListParams, page: number): string {
  const q = new URLSearchParams();
  if (p.q) q.set("q", p.q);
  if (p.consent) q.set("consent", p.consent);
  if (page > 1) q.set("page", String(page));
  const s = q.toString();
  return s ? `/contacts?${s}` : "/contacts";
}
