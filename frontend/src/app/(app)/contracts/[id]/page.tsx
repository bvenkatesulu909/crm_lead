import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import type { ReactNode } from "react";

import { ContractStatusBadge, EndHint } from "@/components/contract-view";
import { Card, Forbidden, SuccessAlert } from "@/components/ui";
import { ApiError } from "@/lib/api-error";
import type { Account, Contract, ContractEvent } from "@/lib/api-types";
import { BILLING_LABELS, eventTitle } from "@/lib/contracts";
import { formatAmounts } from "@/lib/dashboard";
import { formatDate, formatDateTime } from "@/lib/format";
import {
  canManageContracts,
  canWriteContracts,
  hasAny,
} from "@/lib/permissions";
import { apiFetch, getMe } from "@/lib/server/api";

import { contractStep } from "../actions";
import { ContractActions } from "./contract-actions";

export const metadata: Metadata = { title: "Contract" };

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const DONE: Record<string, string> = {
  created: "The contract was created as a draft.",
  updated: "Your changes were saved.",
  activated:
    "The contract is active. The owner will be reminded before it ends.",
  terminated: "The contract was terminated.",
  renewed:
    "The renewal was created as a draft. Review it and activate it to complete the renewal.",
  noted: "The note was added.",
};
const link = "text-brand-700 hover:underline";

export default async function ContractPage({
  params,
  searchParams,
}: PageProps<"/contracts/[id]">) {
  const [{ id }, query] = await Promise.all([params, searchParams]);
  if (!UUID.test(id)) notFound();
  const me = await getMe();
  let contract: Contract;
  try {
    contract = await apiFetch<Contract>(`/contracts/${id}`);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) notFound();
    if (error instanceof ApiError && error.status === 403) return <Forbidden />;
    throw error;
  }
  const [account, history] = await Promise.all([
    apiFetch<Account>(`/accounts/${contract.account_id}`).catch(() => null),
    apiFetch<ContractEvent[]>(`/contracts/${id}/history`).catch(() => []),
  ]);
  const done = typeof query.done === "string" ? DONE[query.done] : undefined;
  const mine =
    contract.owner_id === me.user_id || account?.owner_id === me.user_id;
  const canWrite =
    canWriteContracts(me) && (hasAny(me, "contract:write:all") || mine);
  const step = (s: Parameters<typeof contractStep>[2]) =>
    contractStep.bind(null, contract.id, contract.version, s);

  const period =
    contract.start_date && contract.end_date
      ? `${formatDate(contract.start_date)} – ${formatDate(contract.end_date)}`
      : "Dates not set yet";
  const details: [string, ReactNode][] = [
    ["Account", account ? <Link href={`/accounts/${account.id}`} className={link}>{account.name}</Link> : (contract.account_name ?? "—")],
    ["Owner", contract.owner_name ?? "—"],
    ["Period", period],
    ["Value", `${formatAmounts([{ currency: contract.currency, amount: contract.total_value }])} · ${BILLING_LABELS[contract.billing_frequency]}`],
    ["Renewal reminder", contract.renewal_date ? `${formatDate(contract.renewal_date)} (${contract.renewal_notice_days} days before the end)${contract.renewal_reminded_at ? " - sent" : ""}` : `${contract.renewal_notice_days} days before the end`],
    ["Renewal", `${contract.auto_renew ? "A draft renewal is prepared automatically" : "Renewed by hand"}${contract.renewal_term_months ? ` · ${contract.renewal_term_months} months` : ""}`],
    ...(contract.renewed_from_id ? ([["Renews", <Link key="f" href={`/contracts/${contract.renewed_from_id}`} className={link}>The previous contract</Link>]] as [string, ReactNode][]) : []),
    ...(contract.renewed_to_id ? ([["Renewed by", <Link key="t" href={`/contracts/${contract.renewed_to_id}`} className={link}>The renewal</Link>]] as [string, ReactNode][]) : []),
    ...(contract.termination_reason ? ([["Terminated because", contract.termination_reason]] as [string, ReactNode][]) : []),
  ]; // prettier-ignore

  return (
    <>
      <nav aria-label="Breadcrumb" className="mb-4 text-sm">
        <Link href="/contracts" className={`font-medium ${link}`}>← Contracts</Link>
      </nav>
      {done && <div className="mb-4"><SuccessAlert>{done}</SuccessAlert></div>}
      <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="font-mono text-sm text-slate-500">{contract.label}</p>
          <h1 className="text-2xl font-semibold tracking-tight text-slate-900">{contract.title}</h1>
          <div className="mt-2 flex items-center gap-3">
            <ContractStatusBadge status={contract.status} />
            <EndHint status={contract.status} daysToEnd={contract.days_to_end} />
          </div>
        </div>
        <ContractActions
          key={contract.version}
          id={contract.id}
          status={contract.status}
          hasRenewal={contract.renewed_to_id !== null}
          can={{ write: canWrite, manage: canManageContracts(me) }}
          act={{ activate: step("activate"), terminate: step("terminate"), renew: step("renew"), note: step("note") }}
        />
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="space-y-6 lg:col-span-2">
          <Card>
            <h2 className="border-b border-slate-200 px-5 py-4 text-base font-semibold text-slate-900">Terms</h2>
            {contract.terms ? (
              <p className="whitespace-pre-line px-5 py-4 text-sm text-slate-700">{contract.terms}</p>
            ) : (
              <p className="px-5 py-6 text-sm text-slate-600">No terms recorded yet. Edit the contract to add them.</p>
            )}
          </Card>
        </div>
        <div className="space-y-6">
          <Card>
            <h2 className="border-b border-slate-200 px-5 py-4 text-base font-semibold text-slate-900">Details</h2>
            <dl className="space-y-3 px-5 py-4 text-sm">
              {details.map(([label, value]) => (
                <div key={label}><dt className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</dt><dd className="mt-0.5 text-slate-900">{value}</dd></div>
              ))}
            </dl>
          </Card>
          <Card>
            <h2 className="border-b border-slate-200 px-5 py-4 text-base font-semibold text-slate-900">History</h2>
            <ol className="divide-y divide-slate-100">
              {history.map((h, i) => (
                <li key={`${h.created_at}-${i}`} className="px-5 py-3 text-sm">
                  <p className="font-medium text-slate-900">{eventTitle(h)}</p>
                  <p className="text-xs text-slate-500">{formatDateTime(h.created_at)} · {h.actor_name ?? "The system"}</p>
                  {h.note && <p className="mt-0.5 text-xs text-slate-600">{h.note}</p>}
                </li>
              ))}
            </ol>
          </Card>
        </div>
      </div>
    </>
  ); // prettier-ignore
}
