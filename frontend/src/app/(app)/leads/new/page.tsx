import type { Metadata } from "next";

import { Card, Forbidden, PageHeader } from "@/components/ui";
import { canWriteLeads } from "@/lib/permissions";
import { getMe } from "@/lib/server/api";

import { createLead } from "./actions";
import { initialLeadFormState } from "@/lib/lead-form-state";
import { LeadForm } from "@/components/lead-form";

export const metadata: Metadata = { title: "New lead" };

export default async function NewLeadPage() {
  const me = await getMe();
  // Friendly early answer for users without the permission. The API would refuse anyway.
  if (!canWriteLeads(me)) return <Forbidden />;

  return (
    <>
      <PageHeader
        title="New lead"
        description={
          me.roles.some((r) => r === "sales_agent" || r === "sales_manager")
            ? "You will be the owner of this lead."
            : "The lead will be unassigned until a sales manager assigns it."
        }
      />
      <Card className="max-w-3xl p-6">
        <LeadForm action={createLead} initialState={initialLeadFormState} />
      </Card>
    </>
  );
}
