import {
  LEAD_SORTS,
  LEAD_SOURCES,
  LEAD_STATUSES,
  type LeadSort,
} from "@/lib/api-types";

export const PAGE_SIZE = 20;

export type LeadListParams = {
  q: string;
  status: string;
  source: string;
  priority: string;
  sort: LeadSort;
  page: number;
};

type RawParams = Record<string, string | string[] | undefined>;

const one = (value: string | string[] | undefined) =>
  (Array.isArray(value) ? value[0] : value) ?? "";

/** Reads the URL's search parameters, ignoring anything invalid (falls back to defaults). */
export function parseListParams(raw: RawParams): LeadListParams {
  const status = one(raw.status);
  const source = one(raw.source);
  const priority = one(raw.priority);
  const sort = one(raw.sort);
  const page = Number.parseInt(one(raw.page), 10);
  return {
    q: one(raw.q).trim().slice(0, 100),
    status: (LEAD_STATUSES as readonly string[]).includes(status) ? status : "",
    source: (LEAD_SOURCES as readonly string[]).includes(source) ? source : "",
    priority: ["hot", "warm", "cold"].includes(priority) ? priority : "",
    sort: sort in LEAD_SORTS ? (sort as LeadSort) : "-created_at",
    page: Number.isFinite(page) && page > 0 && page <= 5000 ? page : 1,
  };
}

/** Query string for the backend's GET /leads. */
export function apiQuery(params: LeadListParams): string {
  const query = new URLSearchParams({
    limit: String(PAGE_SIZE),
    offset: String((params.page - 1) * PAGE_SIZE),
    sort: params.sort,
  });
  if (params.q) query.set("q", params.q);
  if (params.status) query.set("status", params.status);
  if (params.source) query.set("source", params.source);
  if (params.priority) query.set("priority", params.priority);
  return query.toString();
}

/** Link to the list page with these parameters (defaults left out to keep URLs short). */
export function pageHref(params: LeadListParams, page: number): string {
  const query = new URLSearchParams();
  if (params.q) query.set("q", params.q);
  if (params.status) query.set("status", params.status);
  if (params.source) query.set("source", params.source);
  if (params.priority) query.set("priority", params.priority);
  if (params.sort !== "-created_at") query.set("sort", params.sort);
  if (page > 1) query.set("page", String(page));
  const text = query.toString();
  return text ? `/leads?${text}` : "/leads";
}

export const hasFilters = (p: LeadListParams) =>
  Boolean(p.q || p.status || p.source || p.priority);
