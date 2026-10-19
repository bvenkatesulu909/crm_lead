import type { Metadata } from "next";
import Link from "next/link";

import { PipelineBoard } from "@/components/pipeline-board";
import {
  ButtonLink,
  Card,
  ErrorAlert,
  Forbidden,
  PageHeader,
  buttonClass,
} from "@/components/ui";
import { ApiError, toErrorInfo } from "@/lib/api-error";
import type {
  AccountPage,
  Board,
  BoardColumn,
  DirectoryUser,
  Me,
} from "@/lib/api-types";
import { formatAmounts } from "@/lib/dashboard";
import {
  canManageOpportunities,
  canWriteOpportunities,
  hasAny,
} from "@/lib/permissions";
import { apiFetch, getMe } from "@/lib/server/api";

import { moveOnBoard } from "./actions";
import { boardQuery } from "./board-params";

export const metadata: Metadata = { title: "Pipeline" };

const field =
  "mt-1 block w-full rounded-md border-0 bg-white px-3 py-2 text-sm text-slate-900 ring-1 ring-inset ring-slate-300 focus:ring-2 focus:ring-brand-600";

/** Display only: the API decides which deals may be moved. */
const mayMove = (me: Me, ownerId: string | null) =>
  canManageOpportunities(me) ||
  (hasAny(me, "opportunity:write:own") && ownerId === me.user_id);

function ClosedColumn({
  column,
  title,
  accountNames,
}: {
  column: BoardColumn;
  title: string;
  accountNames: Record<string, string>;
}) {
  return (
    <Card>
      <div className="flex items-baseline justify-between border-b border-slate-200 px-5 py-3">
        <h2 className="text-sm font-semibold text-slate-900">{title}</h2>
        <span className="text-xs text-slate-500">
          {column.count} · {formatAmounts(column.value)}
        </span>
      </div>
      {column.items.length === 0 ? (
        <p className="px-5 py-4 text-sm text-slate-600">None in the last 30 days.</p>
      ) : (
        <ul className="divide-y divide-slate-100">
          {column.items.map((o) => (
            <li key={o.id} className="flex items-center justify-between gap-3 px-5 py-2 text-sm">
              <Link href={`/opportunities/${o.id}`} className="truncate font-medium text-brand-700 hover:underline">{o.name}</Link>
              <span className="shrink-0 text-xs text-slate-500">
                {accountNames[o.account_id] ?? "Account"}
                {o.amount && ` · ${formatAmounts([{ currency: o.currency, amount: o.amount }])}`}
              </span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  ); // prettier-ignore
}

export default async function PipelinePage({
  searchParams,
}: PageProps<"/opportunities">) {
  const raw = await searchParams;
  const { q, owner, query } = boardQuery(raw);
  const me = await getMe();

  let board: Board;
  let accounts: AccountPage["items"];
  let people: DirectoryUser[];
  try {
    [board, accounts, people] = await Promise.all([
      apiFetch<Board>(`/opportunities/board?${query}`),
      apiFetch<AccountPage>("/accounts?limit=200")
        .then((a) => a.items)
        .catch(() => []),
      apiFetch<DirectoryUser[]>("/users").catch(() => []),
    ]);
  } catch (error) {
    if (error instanceof ApiError && error.status === 403) return <Forbidden />;
    return (
      <>
        <PageHeader title="Pipeline" />
        <ErrorAlert
          title="The pipeline could not be loaded"
          error={toErrorInfo(error)}
        />
      </>
    );
  }
  const accountNames = Object.fromEntries(accounts.map((a) => [a.id, a.name]));
  const ownerNames = Object.fromEntries(
    people.map((p) => [p.id, p.display_name]),
  );
  const writable = board.columns
    .flatMap((c) => c.items)
    .filter((o) => mayMove(me, o.owner_id))
    .map((o) => o.id);
  const salesPeople = people.filter((p) => p.assignable);
  const everyone = hasAny(me, "opportunity:read:all");

  return (
    <>
      <PageHeader
        title="Pipeline"
        description={
          everyone
            ? "Open deals of your organisation by stage. Drag a card or use “Move to…”."
            : "Your open deals by stage. Drag a card or use “Move to…”."
        }
        actions={
          canWriteOpportunities(me) && (
            <ButtonLink href="/opportunities/new">New opportunity</ButtonLink>
          )
        }
      />
      <Card className="mb-6">
        <form role="search" aria-label="Filter pipeline" className="grid gap-4 px-5 py-4 sm:grid-cols-[2fr_1fr_auto]">
          <div>
            <label htmlFor="pipe-q" className="text-sm font-medium text-slate-700">Search</label>
            <input id="pipe-q" name="q" type="search" defaultValue={q} maxLength={100} placeholder="Deal name or next step" className={field} />
          </div>
          {everyone ? (
            <div>
              <label htmlFor="pipe-owner" className="text-sm font-medium text-slate-700">Deal owner</label>
              <select id="pipe-owner" name="owner" defaultValue={owner} className={field}>
                <option value="">Everyone</option>
                {salesPeople.map((p) => <option key={p.id} value={p.id}>{p.display_name}</option>)}
              </select>
            </div>
          ) : <span className="hidden sm:block" />}
          <div className="flex items-end gap-2">
            <button type="submit" className={buttonClass("primary")}>Apply</button>
            {(q || owner) && <Link href="/opportunities" className={buttonClass("secondary")}>Clear</Link>}
          </div>
        </form>
      </Card>

      <PipelineBoard
        columns={board.columns}
        accountNames={accountNames}
        ownerNames={ownerNames}
        writable={writable}
        move={moveOnBoard}
      />

      <div className="mt-6 grid gap-6 lg:grid-cols-2">
        <ClosedColumn column={board.won} title="Won (last 30 days)" accountNames={accountNames} />
        <ClosedColumn column={board.lost} title="Lost (last 30 days)" accountNames={accountNames} />
      </div>
      <p className="mt-4 text-xs text-slate-500">
        Probabilities are fixed per stage (10 / 25 / 50 / 75 %). Weighted value = value × probability.
        Pipelines your organisation can configure come with the administration phase.
      </p>
    </>
  ); // prettier-ignore
}
