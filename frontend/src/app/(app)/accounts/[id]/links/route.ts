import { notFound } from "next/navigation";
import { NextResponse, type NextRequest } from "next/server";

import type { ContactPage, OpportunityPage } from "@/lib/api-types";
import { apiFetch } from "@/lib/server/api";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/**
 * GET /accounts/<id>/links - the contacts and the open deals of ONE account.
 *
 * The quote and opportunity forms offer a contact and a deal that belong to the chosen account.
 * Loading those for every account up front hits the list limit, so the form asks for just the
 * chosen account's. The API decides what this user may see; a list the user may not read (for
 * example contacts, for a role without access) simply comes back empty.
 */
export async function GET(
  _request: NextRequest,
  { params }: RouteContext<"/accounts/[id]/links">,
) {
  const { id } = await params;
  if (!UUID.test(id)) notFound();
  const [contacts, opportunities] = await Promise.all([
    apiFetch<ContactPage>(`/contacts?account_id=${id}&limit=100`)
      .then((page) =>
        page.items.map((c) => ({
          id: c.id,
          name: [c.first_name, c.last_name].filter(Boolean).join(" "),
          accountId: c.account_id,
        })),
      )
      .catch(() => []),
    apiFetch<OpportunityPage>(
      `/opportunities?account_id=${id}&limit=100&stage=prospecting&stage=qualification&stage=proposal&stage=negotiation`,
    )
      .then((page) =>
        page.items.map((o) => ({
          id: o.id,
          name: o.name,
          accountId: o.account_id,
        })),
      )
      .catch(() => []),
  ]);
  return NextResponse.json({ contacts, opportunities });
}
