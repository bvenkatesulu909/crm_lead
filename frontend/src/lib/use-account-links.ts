"use client";

import { useEffect, useState } from "react";

export type LinkOption = { id: string; name: string; accountId: string | null };
export type AccountLinks = {
  contacts: LinkOption[];
  opportunities: LinkOption[];
};

const NONE: AccountLinks = { contacts: [], opportunities: [] };

/**
 * The contacts and open deals of the chosen account, fetched from the server when the account
 * changes (see app/(app)/accounts/[id]/links). Until they arrive, or if the request fails, the
 * lists are empty and the form still works with whatever it was given up front.
 */
export function useAccountLinks(
  accountId: string,
  enabled: boolean,
): AccountLinks {
  const [loaded, setLoaded] = useState<{
    accountId: string;
    links: AccountLinks;
  } | null>(null);

  useEffect(() => {
    if (!enabled || !accountId) return;
    const controller = new AbortController();
    fetch(`/accounts/${accountId}/links`, {
      signal: controller.signal,
      headers: { accept: "application/json" },
    })
      .then((response) => (response.ok ? response.json() : NONE))
      .then((links: AccountLinks) => setLoaded({ accountId, links }))
      .catch(() => {
        // Aborted or failed: keep the form usable without the extra choices.
      });
    return () => controller.abort();
  }, [accountId, enabled]);

  return loaded && loaded.accountId === accountId ? loaded.links : NONE;
}
