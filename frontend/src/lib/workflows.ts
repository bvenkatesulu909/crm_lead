import type {
  RuleAction,
  RuleCondition,
  WorkflowCatalogue,
} from "@/lib/api-types";

/** Plain words for comparisons and roles in the rule editor and summaries. */
export const OPERATOR_LABELS: Record<string, string> = {
  eq: "is",
  neq: "is not",
  in: "is one of",
  gt: "is more than",
  gte: "is at least",
  lt: "is less than",
  lte: "is at most",
};

export const ROLE_NAMES: Record<string, string> = {
  tenant_admin: "an admin",
  sales_manager: "a sales manager",
  sales_agent: "a sales agent",
  support_agent: "a support agent",
};

/** "pending_approval" -> "Pending approval". */
export function optionLabel(code: string): string {
  const text = code.replaceAll("_", " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

function person(who: string, names: Record<string, string>): string {
  if (who === "owner") return "the owner";
  if (who.startsWith("role:"))
    return `every ${ROLE_NAMES[who.slice(5)]?.replace(/^an? /, "") ?? who.slice(5)}`;
  return names[who.slice(5)] ?? "a former colleague";
}

/** One readable sentence per condition / action, for the rule list. */
export function describeCondition(c: RuleCondition, catalogue: WorkflowCatalogue, trigger: string): string {
  const field = catalogue.triggers.find((t) => t.key === trigger)?.fields.find((f) => f.key === c.field);
  const value = Array.isArray(c.value) ? c.value.map(optionLabel).join(", ") : field?.type === "choice" ? optionLabel(c.value) : c.value;
  return `${field?.label ?? c.field} ${OPERATOR_LABELS[c.op] ?? c.op} ${value}`;
} // prettier-ignore

export function describeAction(a: RuleAction, names: Record<string, string>): string {
  if (a.type === "create_task")
    return `Create task "${a.subject}" for ${person(a.assignee, names)}, due in ${a.due_in_days} day${a.due_in_days === 1 ? "" : "s"}`;
  if (a.type === "notify") return `Notify ${person(a.to, names)}: "${a.message}"`;
  return `Set ${a.field === "lead.status" ? "lead status" : "customer segment"} to ${optionLabel(a.value)}`;
} // prettier-ignore
