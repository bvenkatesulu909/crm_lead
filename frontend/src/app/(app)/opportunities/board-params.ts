const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

type Raw = Record<string, string | string[] | undefined>;
const one = (v: string | string[] | undefined) =>
  (Array.isArray(v) ? v[0] : v) ?? "";

/** Reads the board filters from the URL; anything invalid is ignored. */
export function boardQuery(raw: Raw): {
  q: string;
  owner: string;
  query: string;
} {
  const q = one(raw.q).trim().slice(0, 100);
  const owner = UUID.test(one(raw.owner)) ? one(raw.owner).toLowerCase() : "";
  const query = new URLSearchParams({ limit: "50", closed_days: "30" });
  if (q) query.set("q", q);
  if (owner) query.set("owner_id", owner);
  return { q, owner, query: query.toString() };
}
