import type { Metadata } from "next";
import Link from "next/link";

import { ApprovalCard } from "@/components/approval-views";
import { ApprovalDecision } from "@/components/approval-decision";
import { Pagination } from "@/components/pagination";
import {
  Card,
  EmptyState,
  ErrorAlert,
  Forbidden,
  PageHeader,
  SuccessAlert,
  buttonClass,
  cx,
} from "@/components/ui";
import { ApiError, toErrorInfo } from "@/lib/api-error";
import {
  AGENT_ACTION_STATUSES,
  type AgentActionPage,
  type DirectoryUser,
} from "@/lib/api-types";
import {
  APPROVAL_STATUS_LABELS,
  APPROVAL_TABS,
  approvalPageHref,
  approvalQuery,
  canDecideOn,
  parseApprovalFilters,
} from "@/lib/approvals";
import { canApproveActions, canReadApprovals } from "@/lib/permissions";
import { apiFetch, getMe } from "@/lib/server/api";

import { approveProposal, rejectProposal } from "./actions";

export const metadata: Metadata = { title: "Approvals" };

const PAGE_SIZE = 20;
const field =
  "mt-1 block w-full rounded-md border-0 bg-white px-3 py-2 text-sm text-slate-900 ring-1 ring-inset ring-slate-300 focus:ring-2 focus:ring-brand-600";

/**
 * AI proposals (ADR 0014). Approvers (sales managers, tenant admins) decide on proposals made
 * for their colleagues; everyone else sees only their own, so the "Waiting" tab is for
 * approvers and the others start on "My proposals". The API filters this in the database.
 */
export default async function ApprovalsPage({
  searchParams,
}: PageProps<"/approvals">) {
  const raw = await searchParams;
  const me = await getMe();
  if (!canReadApprovals(me)) return <Forbidden />;
  const approver = canApproveActions(me);
  const filters = parseApprovalFilters(raw);
  // Colleagues without approval rights have no organisation-wide queue: show their own.
  const tabs = approver
    ? APPROVAL_TABS
    : APPROVAL_TABS.filter((t) => t.key !== "waiting");
  const tab = tabs.some((t) => t.key === filters.tab)
    ? filters.tab
    : tabs[0].key;
  const effective = { ...filters, tab };

  let data: AgentActionPage;
  try {
    data = await apiFetch<AgentActionPage>(
      `/approvals/actions?${approvalQuery(effective, PAGE_SIZE)}`,
    );
  } catch (error) {
    if (error instanceof ApiError && error.status === 403) return <Forbidden />;
    return (
      <ErrorAlert
        title="Proposals could not be loaded"
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

  return (
    <>
      <PageHeader
        title="Approvals"
        description={
          approver
            ? "Changes the AI assistant proposed. Nothing happens until someone other than the person who asked approves it."
            : "Changes the AI assistant proposed for you. A manager decides on them."
        }
      />
      {typeof raw.done === "string" && (
        <div className="mb-4">
          <SuccessAlert>The decision was saved.</SuccessAlert>
        </div>
      )}
      <nav aria-label="Proposal lists" className="mb-4 flex flex-wrap gap-2">
        {tabs.map((t) => (
          <Link
            key={t.key}
            href={approvalPageHref({ tab: t.key, status: "", page: 1 }, 1)}
            aria-current={t.key === tab ? "page" : undefined}
            className={cx(
              buttonClass(t.key === tab ? "primary" : "secondary"),
              "no-underline",
            )}
          >
            {t.label}
          </Link>
        ))}
      </nav>
      {tab === "all" && (
        <Card className="mb-4">
          <form role="search" aria-label="Filter proposals" className="flex flex-wrap items-end gap-3 px-5 py-4">
            <input type="hidden" name="tab" value="all" />
            <div>
              <label htmlFor="approval-status" className="text-sm font-medium text-slate-700">Status</label>
              <select id="approval-status" name="status" defaultValue={effective.status} className={field}>
                <option value="">All statuses</option>
                {AGENT_ACTION_STATUSES.map((s) => (
                  <option key={s} value={s}>{APPROVAL_STATUS_LABELS[s]}</option>
                ))}
              </select>
            </div>
            <button type="submit" className={buttonClass("primary")}>Apply</button>
          </form>
        </Card>
      )}
      {data.items.length === 0 ? (
        <Card>
          <EmptyState
            title={tab === "waiting" ? "Nothing is waiting" : "No proposals"}
            description={
              tab === "waiting"
                ? "When the AI assistant proposes a change for a colleague, it appears here."
                : "Proposals the AI assistant makes for you appear here."
            }
          />
        </Card>
      ) : (
        <ul className="space-y-4" aria-label="Proposals">
          {data.items.map((a) => (
            <li key={a.id}>
              <ApprovalCard
                action={a}
                people={people}
                me={me}
                decision={
                  canDecideOn(me, a) ? (
                    <>
                      <Link href={`/approvals/${a.id}`} className={buttonClass("secondary")}>
                        Details
                      </Link>
                      <ApprovalDecision
                        description={a.description}
                        approve={approveProposal.bind(null, a.id, a.version)}
                        reject={rejectProposal.bind(null, a.id, a.version)}
                      />
                    </>
                  ) : undefined
                }
              />
            </li>
          ))}
        </ul>
      )}
      {data.total > 0 && (
        <div className="mt-4">
          <Pagination
            total={data.total}
            page={effective.page}
            pageSize={PAGE_SIZE}
            hrefForPage={(p) => approvalPageHref(effective, p)}
          />
        </div>
      )}
    </>
  ); // prettier-ignore
}
