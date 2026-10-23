import type {
  BillingFrequency,
  ContractEvent,
  ContractStatus,
} from "@/lib/api-types";

/** Contract labels and small display helpers (the server decides everything that matters). */

export const CONTRACT_STATUS_LABELS: Record<ContractStatus, string> = {
  draft: "Draft",
  active: "Active",
  expired: "Expired",
  terminated: "Terminated",
  renewed: "Renewed",
};

export const CONTRACT_STATUS_STYLE: Record<ContractStatus, string> = {
  draft: "bg-slate-100 text-slate-700",
  active: "bg-emerald-50 text-emerald-700",
  expired: "bg-amber-50 text-amber-800",
  terminated: "bg-red-50 text-red-700",
  renewed: "bg-brand-50 text-brand-700",
};

export const BILLING_LABELS: Record<BillingFrequency, string> = {
  one_time: "One time",
  monthly: "Monthly",
  quarterly: "Quarterly",
  annually: "Annually",
};

export const EVENT_LABELS: Record<ContractEvent["event_type"], string> = {
  created: "Created",
  status_changed: "Status changed",
  note: "Note",
  renewal_reminder: "Renewal reminder",
  expired: "Expired",
};

export type EndHint = {
  text: string;
  /** "soon" = inside the next 30 days, "late" = the end date has passed. */
  tone: "none" | "ok" | "soon" | "late";
};

/** "Ends in 20 days" / "Ended 3 days ago" - only for contracts that are still running. */
export function endHint(contract: {
  status: ContractStatus;
  days_to_end: number | null;
}): EndHint {
  const days = contract.days_to_end;
  if (contract.status !== "active" || days === null)
    return { text: "", tone: "none" };
  if (days < 0)
    return {
      text: `Ended ${-days} day${days === -1 ? "" : "s"} ago`,
      tone: "late",
    };
  if (days === 0) return { text: "Ends today", tone: "soon" };
  return {
    text: `Ends in ${days} day${days === 1 ? "" : "s"}`,
    tone: days <= 30 ? "soon" : "ok",
  };
}

export const END_HINT_STYLE: Record<EndHint["tone"], string> = {
  none: "",
  ok: "text-slate-500",
  soon: "text-amber-700",
  late: "text-red-700",
};

/** A short sentence for one history entry. */
export function eventTitle(event: ContractEvent): string {
  if (event.event_type === "status_changed" && event.to_status)
    return `Status: ${CONTRACT_STATUS_LABELS[event.to_status]}`;
  if (event.event_type === "created") return "Created as a draft";
  if (event.event_type === "expired") return "Expired";
  return EVENT_LABELS[event.event_type];
}
