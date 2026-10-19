import type { Metadata } from "next";
import Link from "next/link";

import { Pagination } from "@/components/pagination";
import {
  ButtonLink,
  Card,
  EmptyState,
  ErrorAlert,
  Forbidden,
  PageHeader,
  AccountStatus,
  SuccessAlert,
  buttonClass,
  cx,
} from "@/components/ui";
import { ApiError, toErrorInfo } from "@/lib/api-error";
import {
  LIFECYCLE_STAGES,
  SEGMENTS,
  type AccountPage,
  type DirectoryUser,
} from "@/lib/api-types";
import {
  COUNTRIES,
  LIFECYCLE_LABELS,
  SEGMENT_LABELS,
  countryName,
} from "@/lib/customer-data";
import { formatDate } from "@/lib/format";
import { canManageAccounts, canWriteAccounts, hasAny } from "@/lib/permissions";
import { apiFetch, getMe } from "@/lib/server/api";

import { restoreAccount } from "./actions";
import {
  ACCOUNT_PAGE_SIZE,
  accountApiQuery,
  accountPageHref,
  parseAccountParams,
} from "./list-params";
import { RestoreButton } from "./restore-button";

export const metadata: Metadata = { title: "Accounts" };

const field =
  "mt-1 block w-full rounded-md border-0 bg-white px-3 py-2 text-sm text-slate-900 ring-1 ring-inset ring-slate-300 focus:ring-2 focus:ring-brand-600";

export default async function AccountsPage({
  searchParams,
}: PageProps<"/accounts">) {
  const raw = await searchParams;
  const params = parseAccountParams(raw);
  const me = await getMe();
  const manager = canManageAccounts(me);
  if (params.archived && !manager) return <Forbidden />;

  let data: AccountPage;
  let people: DirectoryUser[];
  try {
    // The backend decides which accounts this user may see (own vs. all, own tenant only).
    [data, people] = await Promise.all([
      apiFetch<AccountPage>(`/accounts?${accountApiQuery(params)}`),
      apiFetch<DirectoryUser[]>("/users"),
    ]);
  } catch (error) {
    if (error instanceof ApiError && error.status === 403) return <Forbidden />;
    return (
      <>
        <PageHeader title="Accounts" />
        <ErrorAlert
          title="Accounts could not be loaded"
          error={toErrorInfo(error)}
        />
      </>
    );
  }
  const ownerName = (id: string | null) =>
    id === null
      ? "—"
      : (people.find((p) => p.id === id)?.display_name ?? "Former colleague");
  const filtered = Boolean(
    params.q ||
    params.status ||
    params.segment ||
    params.country ||
    params.lifecycle,
  );
  const tab = (archived: boolean, label: string) => (
    <Link
      href={archived ? "/accounts?archived=1" : "/accounts"}
      aria-current={params.archived === archived ? "page" : undefined}
      className={cx(
        "rounded-full px-4 py-1.5 text-sm font-medium ring-1 ring-inset",
        params.archived === archived
          ? "bg-brand-600 text-white ring-brand-600"
          : "bg-white text-slate-700 ring-slate-300 hover:bg-slate-50",
      )}
    >
      {label}
    </Link>
  );

  return (
    <>
      <PageHeader
        title="Accounts"
        description={
          params.archived
            ? "Archived accounts. Nothing was deleted; restore an account to bring it back."
            : hasAny(me, "account:read:all")
              ? "All customer accounts of your organisation."
              : "Customer accounts you own."
        }
        actions={
          canWriteAccounts(me) &&
          !params.archived && (
            <ButtonLink href="/accounts/new">New account</ButtonLink>
          )
        }
      />
      {raw.done === "archived" && (
        <div className="mb-4">
          <SuccessAlert>
            The account was archived. Managers can restore it under
            &ldquo;Archived&rdquo;.
          </SuccessAlert>
        </div>
      )}
      <nav aria-label="Account lists" className="mb-4 flex gap-2">
        {tab(false, "Accounts")}
        <Link
          href="/accounts/health"
          className="rounded-full bg-white px-4 py-1.5 text-sm font-medium text-slate-700 ring-1 ring-inset ring-slate-300 hover:bg-slate-50"
        >
          Customer health
        </Link>
        {manager && tab(true, "Archived")}
      </nav>
      <Card>
        <form
          role="search"
          aria-label="Filter accounts"
          className="grid gap-4 px-5 py-4 sm:grid-cols-2 lg:grid-cols-[2fr_1fr_1fr_1fr_1fr_auto]"
        >
          {params.archived && <input type="hidden" name="archived" value="1" />}
          <div>
            <label
              htmlFor="account-q"
              className="text-sm font-medium text-slate-700"
            >
              Search
            </label>
            <input
              id="account-q"
              name="q"
              type="search"
              defaultValue={params.q}
              maxLength={100}
              placeholder="Name or account number"
              className={field}
            />
          </div>
          <div>
            <label
              htmlFor="account-status"
              className="text-sm font-medium text-slate-700"
            >
              Status
            </label>
            <select
              id="account-status"
              name="status"
              defaultValue={params.status}
              className={field}
            >
              <option value="">All statuses</option>
              <option value="active">Active</option>
              <option value="inactive">Inactive</option>
            </select>
          </div>
          <div>
            <label
              htmlFor="account-segment"
              className="text-sm font-medium text-slate-700"
            >
              Segment
            </label>
            <select
              id="account-segment"
              name="segment"
              defaultValue={params.segment}
              className={field}
            >
              <option value="">All segments</option>
              {SEGMENTS.map((segment) => (
                <option key={segment} value={segment}>
                  {SEGMENT_LABELS[segment]}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label
              htmlFor="account-country"
              className="text-sm font-medium text-slate-700"
            >
              Country
            </label>
            <select
              id="account-country"
              name="country"
              defaultValue={params.country}
              className={field}
            >
              <option value="">All countries</option>
              {COUNTRIES.map(([code, name]) => (
                <option key={code} value={code}>
                  {name}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label
              htmlFor="account-lifecycle"
              className="text-sm font-medium text-slate-700"
            >
              Lifecycle
            </label>
            <select
              id="account-lifecycle"
              name="lifecycle"
              defaultValue={params.lifecycle}
              className={field}
            >
              <option value="">All stages</option>
              {LIFECYCLE_STAGES.map((stage) => (
                <option key={stage} value={stage}>
                  {LIFECYCLE_LABELS[stage]}
                </option>
              ))}
            </select>
          </div>
          <div className="flex items-end gap-2">
            <button type="submit" className={buttonClass("primary")}>
              Apply
            </button>
            {filtered && (
              <Link
                href={params.archived ? "/accounts?archived=1" : "/accounts"}
                className={buttonClass("secondary")}
              >
                Clear
              </Link>
            )}
          </div>
        </form>

        <div className="border-t border-slate-200">
          {data.items.length === 0 ? (
            filtered ? (
              <EmptyState
                title="No accounts match your search"
                description="Try other words or remove the filter."
                action={
                  <ButtonLink href="/accounts" variant="secondary">
                    Clear filters
                  </ButtonLink>
                }
              />
            ) : (
              <EmptyState
                title={
                  params.archived ? "No archived accounts" : "No accounts yet"
                }
                description={
                  params.archived
                    ? "Archived accounts appear here."
                    : "Create an account, or convert a qualified lead into one."
                }
              />
            )
          ) : (
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-slate-200 text-sm">
                <caption className="sr-only">
                  Customer accounts, page {params.page}
                </caption>
                <thead className="bg-slate-50 text-left text-xs font-semibold uppercase tracking-wide text-slate-600">
                  <tr>
                    <th scope="col" className="px-5 py-3">
                      Name
                    </th>
                    <th scope="col" className="hidden px-5 py-3 md:table-cell">
                      Lifecycle
                    </th>
                    <th scope="col" className="hidden px-5 py-3 lg:table-cell">
                      Segment
                    </th>
                    <th scope="col" className="px-5 py-3">
                      Status
                    </th>
                    <th scope="col" className="hidden px-5 py-3 sm:table-cell">
                      Owner
                    </th>
                    <th scope="col" className="hidden px-5 py-3 lg:table-cell">
                      Created
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 bg-white">
                  {data.items.map((account) => (
                    <tr key={account.id} className="hover:bg-slate-50">
                      <th
                        scope="row"
                        className="text-left px-5 py-3 font-medium"
                      >
                        {params.archived ? (
                          <span className="flex flex-wrap items-center gap-3">
                            {account.name}
                            <RestoreButton
                              name={account.name}
                              restore={restoreAccount.bind(
                                null,
                                account.id,
                                account.version,
                              )}
                            />
                          </span>
                        ) : (
                          <Link
                            href={`/accounts/${account.id}`}
                            className="text-brand-700 hover:underline"
                          >
                            {account.name}
                          </Link>
                        )}
                      </th>
                      <td className="hidden px-5 py-3 text-slate-700 md:table-cell">
                        {account.lifecycle_stage
                          ? LIFECYCLE_LABELS[account.lifecycle_stage]
                          : "—"}
                        {account.country && (
                          <span className="block text-xs text-slate-500">
                            {countryName(account.country)}
                          </span>
                        )}
                      </td>
                      <td className="hidden px-5 py-3 text-slate-700 lg:table-cell">
                        {account.segment
                          ? SEGMENT_LABELS[account.segment]
                          : "—"}
                      </td>
                      <td className="px-5 py-3">
                        <AccountStatus status={account.status} />
                      </td>
                      <td className="hidden px-5 py-3 text-slate-700 sm:table-cell">
                        {ownerName(account.owner_id)}
                      </td>
                      <td className="hidden whitespace-nowrap px-5 py-3 text-slate-700 lg:table-cell">
                        {formatDate(account.created_at)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
        {data.total > 0 && (
          <div className="border-t border-slate-200">
            <Pagination
              total={data.total}
              page={params.page}
              pageSize={ACCOUNT_PAGE_SIZE}
              hrefForPage={(page) => accountPageHref(params, page)}
            />
          </div>
        )}
      </Card>
    </>
  );
}
