/**
 * Saved account filters (ADR 0042, BR-pre). A saved filter is a name plus the Accounts list's own
 * filter parameters; applying one is the same as typing those filters on the list. The API checks
 * every value again, so nothing here is a security boundary.
 */
export type SavedFilter = {
  id: string;
  record_type: "account";
  name: string;
  params: Record<string, string>;
  shared: boolean;
  owner_user_id: string;
  /** True when the signed-in person owns it (display only: the API decides who may change it). */
  mine: boolean;
  version: number;
  created_at: string;
  updated_at: string;
};

export type SavedFilterPage = { items: SavedFilter[] };

/** The list's URL names for the filters the screen can show, in the API's names. */
const URL_TO_API: Record<string, string> = {
  q: "q",
  status: "status",
  segment: "segment",
  country: "country",
  lifecycle: "lifecycle_stage",
};
const API_TO_URL = Object.fromEntries(
  Object.entries(URL_TO_API).map(([url, api]) => [api, url]),
);

/** The conditions of the current list, as the API stores them. Empty values are left out. */
export function paramsFromList(list: {
  q: string;
  status: string;
  segment: string;
  country: string;
  lifecycle: string;
}): Record<string, string> {
  const params: Record<string, string> = {};
  for (const [urlKey, apiKey] of Object.entries(URL_TO_API)) {
    const value = (list as Record<string, string>)[urlKey];
    if (value) params[apiKey] = value;
  }
  return params;
}

/**
 * The list address that applies a saved filter. Conditions the list screen has no box for
 * (a filter made by another tool) are not part of the address; the screen says so.
 */
export function hrefForSavedFilter(filter: SavedFilter): string {
  const query = new URLSearchParams();
  for (const [apiKey, value] of Object.entries(filter.params)) {
    const urlKey = API_TO_URL[apiKey];
    if (urlKey) query.set(urlKey, value);
  }
  const text = query.toString();
  return text ? `/accounts?${text}` : "/accounts";
}

/** True when the filter holds a condition the list screen cannot show. */
export function hasHiddenConditions(filter: SavedFilter): boolean {
  return Object.keys(filter.params).some((key) => !(key in API_TO_URL));
}

/** True when the current list is exactly this saved filter (to mark it as selected). */
export function matchesList(
  filter: SavedFilter,
  list: Record<string, string>,
): boolean {
  const mine = paramsFromList(list as never);
  const theirs = filter.params;
  const keys = new Set([...Object.keys(mine), ...Object.keys(theirs)]);
  return [...keys].every((key) => mine[key] === theirs[key]);
}
