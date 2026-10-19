import { describe, expect, it } from "vitest";

import type { WorkflowCatalogue } from "@/lib/api-types";
import {
  describeAction,
  describeCondition,
  optionLabel,
} from "@/lib/workflows";

const catalogue: WorkflowCatalogue = {
  triggers: [
    {
      key: "quote.approval_requested",
      label: "A quote needs approval",
      kind: "event",
      record_type: "quote",
      days_label: null,
      fields: [
        {
          key: "max_discount_percent",
          label: "Largest line discount (%)",
          type: "number",
          options: [],
        },
        {
          key: "status",
          label: "Quote status",
          type: "choice",
          options: ["sent", "pending_approval"],
        },
      ],
      field_updates: [],
    },
  ],
  operators: { number: ["gt"], choice: ["eq", "in"] },
  roles: ["sales_manager"],
  max_conditions: 5,
  max_actions: 5,
};

describe("automation rule summaries", () => {
  it("describes conditions in plain words", () => {
    const t = "quote.approval_requested";
    expect(describeCondition({ field: "max_discount_percent", op: "gt", value: "20" }, catalogue, t)).toBe(
      "Largest line discount (%) is more than 20",
    );
    expect(describeCondition({ field: "status", op: "in", value: ["sent", "pending_approval"] }, catalogue, t)).toBe(
      "Quote status is one of Sent, Pending approval",
    );
  }); // prettier-ignore

  it("describes actions with people's names", () => {
    const names = { "u-1": "Morgan Manager" };
    expect(describeAction({ type: "create_task", subject: "Check {record}", due_in_days: 1, assignee: "owner" }, names)).toBe(
      'Create task "Check {record}" for the owner, due in 1 day',
    );
    expect(describeAction({ type: "notify", message: "Look", to: "role:sales_manager" }, names)).toBe('Notify every sales manager: "Look"');
    expect(describeAction({ type: "notify", message: "Look", to: "user:u-1" }, names)).toBe('Notify Morgan Manager: "Look"');
    expect(describeAction({ type: "notify", message: "Look", to: "user:gone" }, names)).toBe('Notify a former colleague: "Look"');
    expect(describeAction({ type: "update_field", field: "lead.status", value: "contacted" }, names)).toBe("Set lead status to Contacted");
  }); // prettier-ignore

  it("turns codes into labels", () => {
    expect(optionLabel("pending_approval")).toBe("Pending approval");
  });
});
