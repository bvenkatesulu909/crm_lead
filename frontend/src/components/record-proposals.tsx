import { RecordProposalsList } from "@/components/approval-views";
import type { AgentActionPage, Me } from "@/lib/api-types";
import { canReadApprovals } from "@/lib/permissions";
import { apiFetch } from "@/lib/server/api";

/**
 * On a lead, account or contact page: AI proposals waiting for this record (ADR 0014). Like the
 * lead score, it is extra information - the page works without it - and the API only returns
 * proposals the reader may see (approvers: all; others: their own).
 */
export async function RecordProposals({
  me,
  targetId,
}: {
  me: Pick<Me, "permissions">;
  targetId: string;
}) {
  if (!canReadApprovals(me)) return null;
  const page = await apiFetch<AgentActionPage>(
    `/approvals/actions?target_id=${encodeURIComponent(targetId)}&status=pending&limit=10`,
  ).catch(() => null);
  return page ? <RecordProposalsList items={page.items} /> : null;
}
