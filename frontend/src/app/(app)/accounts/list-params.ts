import { LIFECYCLE_STAGES, SEGMENTS } from "@/lib/api-types";

export const ACCOUNT_PAGE_SIZE = 20;
export const ACCOUNT_STATUSES = ["active", "inactive"] as const;

export type AccountListParams = {
  q: string;
  status: string;
  segment: string;
  country: string;
  lifecycle: string;
  /** Managers only: show archived accounts instead (the API refuses it for others). */
  archived: boolean;
  page: number;
};

type RawParams = Record<string, string | string[] | undefined>;
const one = (value: string | string[] | undefined) =>
  (Array.isArray(value) ? value[0] : value) ?? "";

/** Reads the URL's search parameters; anything invalid falls back to the default. */
export function parseAccountParams(raw: RawParams): AccountListParams {
  const status = one(raw.status);
  const segment = one(raw.segment);
  const country = one(raw.country).toUpperCase();
  const lifecycle = one(raw.lifecycle);
  const page = Number.parseInt(one(raw.page), 10);
  return {
    q: one(raw.q).trim().slice(0, 100),
    status: (ACCOUNT_STATUSES as readonly string[]).includes(status)
      ? status
      : "",
    segment: (SEGMENTS as readonly string[]).includes(segment) ? segment : "",
    country: /^[A-Z]{2}$/.test(country) ? country : "",
    lifecycle: (LIFECYCLE_STAGES as readonly string[]).includes(lifecycle)
      ? lifecycle
      : "",
    archived: one(raw.archived) === "1",
    page: Number.isFinite(page) && page > 0 && page <= 5000 ? page : 1,
  };
}

/** Query string for the backend's GET /accounts. */
export function accountApiQuery(params: AccountListParams): string {
  const query = new URLSearchParams({
    limit: String(ACCOUNT_PAGE_SIZE),
    offset: String((params.page - 1) * ACCOUNT_PAGE_SIZE),
  });
  if (params.q) query.set("q", params.q);
  if (params.status) query.set("status", params.status);
  if (params.segment) query.set("segment", params.segment);
  if (params.country) query.set("country", params.country);
  if (params.lifecycle) query.set("lifecycle_stage", params.lifecycle);
  if (params.archived) query.set("archived", "true");
  return query.toString();
}

export function accountPageHref(
  params: AccountListParams,
  page: number,
): string {
  const query = new URLSearchParams();
  if (params.q) query.set("q", params.q);
  if (params.status) query.set("status", params.status);
  if (params.segment) query.set("segment", params.segment);
  if (params.country) query.set("country", params.country);
  if (params.lifecycle) query.set("lifecycle", params.lifecycle);
  if (params.archived) query.set("archived", "1");
  if (page > 1) query.set("page", String(page));
  const text = query.toString();
  return text ? `/accounts?${text}` : "/accounts";
}
