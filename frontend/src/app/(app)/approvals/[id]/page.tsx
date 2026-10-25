import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { ApprovalCard } from "@/components/approval-views";
import { ApprovalDecision } from "@/components/approval-decision";
import { ErrorAlert, Forbidden, SuccessAlert } from "@/components/ui";
import { ApiError, toErrorInfo } from "@/lib/api-error";
import type { AgentAction, DirectoryUser } from "@/lib/api-types";
import { canDecideOn } from "@/lib/approvals";
import { canReadApprovals } from "@/lib/permissions";
import { apiFetch, getMe } from "@/lib/server/api";

import { approveProposal, rejectProposal } from "../actions";

export const metadata: Metadata = { title: "AI proposal" };

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const DONE: Record<string, string> = {
  approved: "The proposal was approved. See the result below.",
  rejected: "The proposal was rejected. The colleague who asked is told.",
};

/** One proposal. Notifications link here; approvers decide from here. */
export default async function ApprovalPage({
  params,
  searchParams,
}: PageProps<"/approvals/[id]">) {
  const [{ id }, query] = await Promise.all([params, searchParams]);
  if (!UUID.test(id)) notFound();
  const me = await getMe();
  if (!canReadApprovals(me)) return <Forbidden />;

  let action: AgentAction;
  try {
    action = await apiFetch<AgentAction>(`/approvals/actions/${id}`);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) notFound();
    if (error instanceof ApiError && error.status === 403) return <Forbidden />;
    return (
      <ErrorAlert
        title="The proposal could not be loaded"
        error={toErrorInfo(error)}
      />
    );
  }
  const people = Object.fromEntries(
    (await apiFetch<DirectoryUser[]>("/users").catch(() => [])).map((p) => [
      p.id,
      p.display_name,
    ]),
  );
  const done = typeof query.done === "string" ? DONE[query.done] : undefined;

  return (
    <>
      <nav aria-label="Breadcrumb" className="mb-4 text-sm">
        <Link
          href="/approvals"
          className="font-medium text-brand-700 hover:underline"
        >
          ← Approvals
        </Link>
      </nav>
      {done && (
        <div className="mb-4">
          <SuccessAlert>{done}</SuccessAlert>
        </div>
      )}
      <ApprovalCard
        action={action}
        people={people}
        me={me}
        headingLevel={2}
        decision={
          canDecideOn(me, action) ? (
            <ApprovalDecision
              description={action.description}
              approve={approveProposal.bind(null, action.id, action.version)}
              reject={rejectProposal.bind(null, action.id, action.version)}
            />
          ) : undefined
        }
      />
      {action.status === "pending" &&
        action.requested_by_user_id === me.user_id && (
          <p className="mt-3 text-sm text-slate-600">
            You asked for this, so someone else has to decide on it.
          </p>
        )}
    </>
  );
}
