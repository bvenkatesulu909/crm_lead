import type { Lead, LeadStatus, Me } from "@/lib/api-types";
import { hasAny } from "@/lib/permissions";

/**
 * Which buttons to SHOW on a lead page. A copy of the backend rules (backend/app/modules/
 * leads/transitions.py and policies.py) for display only: if this ever drifts, the API still
 * refuses the action and the page shows the API's explanation.
 */
export const ALLOWED_TRANSITIONS: Record<LeadStatus, LeadStatus[]> = {
  new: ["contacted", "qualified", "unqualified"],
  contacted: ["qualified", "unqualified"],
  qualified: ["contacted", "unqualified", "converted"],
  unqualified: ["contacted"],
  converted: [],
};

export type LeadActions = {
  edit: boolean;
  assign: boolean;
  markContacted: boolean;
  qualify: boolean;
  disqualify: boolean;
  convert: boolean;
};

export function availableActions(
  lead: Pick<Lead, "status" | "owner_id">,
  me: Pick<Me, "permissions" | "user_id">,
): LeadActions {
  const open = lead.status !== "converted";
  const writable =
    hasAny(me, "lead:write:all") ||
    (hasAny(me, "lead:write:own") &&
      lead.owner_id !== null &&
      lead.owner_id === me.user_id);
  const can = (target: LeadStatus) =>
    ALLOWED_TRANSITIONS[lead.status].includes(target);
  return {
    edit: open && writable,
    assign: open && hasAny(me, "lead:assign"),
    markContacted: open && writable && can("contacted"),
    qualify: open && writable && can("qualified"),
    disqualify: open && writable && can("unqualified"),
    convert:
      writable &&
      hasAny(me, "lead:convert") &&
      hasAny(me, "account:write:all", "account:write:own") &&
      can("converted"),
  };
}
