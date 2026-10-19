import type { Me, OrderStatus } from "@/lib/api-types";
import { hasAny } from "@/lib/permissions";

/**
 * Which order buttons to SHOW. Copy of backend/app/modules/orders/rules.py for display only;
 * the API enforces the real rules (and permissions) and its error is shown if they differ.
 */
export const ORDER_TRANSITIONS: Record<OrderStatus, OrderStatus[]> = {
  draft: ["confirmed", "cancelled"],
  confirmed: ["in_fulfilment", "shipped", "cancelled"],
  in_fulfilment: ["shipped", "cancelled"],
  shipped: ["delivered"],
  delivered: [],
  cancelled: [],
};

export type OrderTarget = Exclude<OrderStatus, "draft">;
const FULFILMENT: OrderStatus[] = ["in_fulfilment", "shipped", "delivered"];

/** Status changes this user may try on an order in `status`. */
export function orderActionsFor(
  me: Pick<Me, "permissions">,
  status: OrderStatus,
): OrderTarget[] {
  const write = hasAny(me, "order:write:all", "order:write:own_accounts");
  const fulfil = hasAny(me, "order:fulfil");
  return ORDER_TRANSITIONS[status].filter((target): target is OrderTarget => {
    if (target === "draft") return false;
    if (FULFILMENT.includes(target)) return write && fulfil;
    if (target === "cancelled" && status === "in_fulfilment")
      return write && fulfil;
    return write;
  });
}

export const ORDER_ACTIONS: Record<
  OrderTarget,
  { label: string; confirm: string; danger?: boolean; primary?: boolean }
> = {
  confirmed: {
    label: "Confirm order",
    confirm:
      "Lines and prices are frozen and the customer can see the order in their portal.",
    primary: true,
  },
  in_fulfilment: {
    label: "Start fulfilment",
    confirm: "The warehouse starts preparing this order.",
  },
  shipped: {
    label: "Mark as shipped",
    confirm:
      "The customer sees that the order is on its way, with the tracking reference if you enter one.",
    primary: true,
  },
  delivered: {
    label: "Mark as delivered",
    confirm: "Delivered is final: the order can no longer be changed.",
    primary: true,
  },
  cancelled: {
    label: "Cancel order",
    confirm:
      "Cancelling is final. The customer will see the reason you enter here.",
    danger: true,
  },
};
