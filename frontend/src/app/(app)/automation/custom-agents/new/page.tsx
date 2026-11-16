import type { Metadata } from "next";

import { createCustomAgent } from "@/app/(app)/custom-agents/actions";
import { CustomAgentForm } from "@/components/custom-agent-form";
import { Card, Forbidden, PageHeader } from "@/components/ui";
import type { CustomAgentMenus } from "@/lib/api-types";
import { canManageCustomAgents } from "@/lib/permissions";
import { initialFormState } from "@/lib/form-state";
import { apiFetch, getMe } from "@/lib/server/api";

export const metadata: Metadata = { title: "New custom agent" };

/** Define a new custom agent (ADR 0034). It starts switched off. */
export default async function NewCustomAgentPage() {
  const me = await getMe();
  if (!canManageCustomAgents(me)) return <Forbidden />;
  const menus = await apiFetch<CustomAgentMenus>("/custom-agents/menus");
  return (
    <>
      <PageHeader
        title="New custom agent"
        description="Tell the agent what it is for, what it may read and what it may suggest. It starts switched off: try it on a real record first."
      />
      <Card className="p-5">
        <CustomAgentForm
          menus={menus}
          initial={{
            name: "",
            purpose: "",
            instruction: "",
            read_sets: [],
            suggestion_kinds: [],
          }}
          initialState={initialFormState}
          action={createCustomAgent}
          submitLabel="Create the agent"
        />
      </Card>
    </>
  );
}
