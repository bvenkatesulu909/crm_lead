import type { Metadata } from "next";

import { ButtonLink, Card, Forbidden, PageHeader } from "@/components/ui";
import {
  canReadAccounts,
  canReadDocuments,
  canReadOpportunities,
} from "@/lib/permissions";
import { getMe } from "@/lib/server/api";

export const metadata: Metadata = { title: "Documents" };

/** Where documents live: on customer accounts and deals (quote PDFs on their quotes). */
export default async function DocumentsPage() {
  const me = await getMe();
  if (!canReadDocuments(me)) return <Forbidden />;
  return (
    <>
      <PageHeader title="Documents" description="Files belong to a customer or a deal, so they always follow the same access rules." />
      <div className="grid gap-6 md:grid-cols-3">
        <Card className="p-5 text-sm">
          <h2 className="font-semibold text-slate-900">Customer documents</h2>
          <p className="mt-1 text-slate-600">Contracts, offers and other files on a customer account. Mark a file &ldquo;Visible to the customer&rdquo; to share it in the portal.</p>
          {canReadAccounts(me) && <ButtonLink href="/accounts" variant="secondary" className="mt-3">Open accounts</ButtonLink>}
        </Card>
        <Card className="p-5 text-sm">
          <h2 className="font-semibold text-slate-900">Deal documents</h2>
          <p className="mt-1 text-slate-600">Working files for a deal: requirements, proposals, notes. Always internal.</p>
          {canReadOpportunities(me) && <ButtonLink href="/opportunities" variant="secondary" className="mt-3">Open pipeline</ButtonLink>}
        </Card>
        <Card className="p-5 text-sm">
          <h2 className="font-semibold text-slate-900">Versions and rules</h2>
          <ul className="mt-1 list-disc space-y-1 pl-4 text-slate-600">
            <li>Uploading a file with the same name adds a new version; older versions stay available.</li>
            <li>PDF, images, text/CSV, Word, Excel, PowerPoint, OpenDocument - up to 20 MB.</li>
            <li>Quote PDFs are stored automatically when a quote is sent.</li>
          </ul>
        </Card>
      </div>
    </>
  ); // prettier-ignore
}
