import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { OrderForm } from "@/components/order-form";
import {
  OrderProgress,
  OrderStatusBadge,
  PortalOrderList,
  formatMoney,
  formatQuantity,
  orderNumber,
} from "@/components/orders";
import { type FormState, initialFormState } from "@/lib/form-state";
import {
  centsToDecimal,
  previewLine,
  sumLines,
  toScaled,
} from "@/lib/order-math";
import { orderActionsFor } from "@/lib/order-rules";
import {
  canReadOrders,
  canWriteOrders,
  navigationFor,
} from "@/lib/permissions";
import { orderHeaderSchema, orderLineSchema } from "@/lib/validation/orders";

/** Phase 12: orders - display rules, exact money preview, input checks, components. */

const me = (...permissions: string[]) => ({ permissions });
const AGENT = me("order:read:own_accounts", "order:write:own_accounts");
const MANAGER = me("order:read:all", "order:write:all", "order:fulfil");
const SUPPORT = me("order:read:all");

describe("money preview (exact, like the server)", () => {
  it("parses decimals into whole units without floats", () => {
    expect(toScaled("19.99", 2)).toBe(BigInt(1999));
    expect(toScaled("1.5", 3)).toBe(BigInt(1500));
    expect(toScaled("1.001", 2)).toBeNull(); // too many decimals
    expect(toScaled("-1", 2)).toBeNull();
    expect(toScaled("1e3", 2)).toBeNull();
  });

  it("matches the backend's line amounts and half-up rounding", () => {
    const line = previewLine("3", "19.99", "19");
    expect(line && centsToDecimal(line.total)).toBe("71.36");
    const second = previewLine("1.5", "80", "19");
    expect(centsToDecimal(sumLines([line, second]).total)).toBe("214.16");
    // 0.05 * 50 % = 0.025 -> 0.03 (half up, per line)
    const tiny = previewLine("1", "0.05", "50");
    expect(tiny && centsToDecimal(tiny.tax)).toBe("0.03");
    expect(centsToDecimal(previewLine("3", "0.10", "0")!.total)).toBe("0.30");
  });

  it("shows nothing for incomplete lines", () => {
    expect(previewLine("0", "10", "0")).toBeNull();
    expect(previewLine("1", "", "0")).toBeNull();
    expect(previewLine("1", "10", "101")).toBeNull();
    expect(centsToDecimal(sumLines([null]).total)).toBe("0.00");
  });
});

describe("which order actions are offered (display only)", () => {
  it("agents confirm and cancel, but never run fulfilment", () => {
    expect(orderActionsFor(AGENT, "draft")).toEqual(["confirmed", "cancelled"]);
    expect(orderActionsFor(AGENT, "confirmed")).toEqual(["cancelled"]);
    expect(orderActionsFor(AGENT, "in_fulfilment")).toEqual([]);
  });

  it("fulfilment staff move orders to delivery; final states offer nothing", () => {
    expect(orderActionsFor(MANAGER, "confirmed")).toEqual(["in_fulfilment", "shipped", "cancelled"]);
    expect(orderActionsFor(MANAGER, "in_fulfilment")).toEqual(["shipped", "cancelled"]);
    expect(orderActionsFor(MANAGER, "shipped")).toEqual(["delivered"]);
    expect(orderActionsFor(MANAGER, "delivered")).toEqual([]);
    expect(orderActionsFor(MANAGER, "cancelled")).toEqual([]);
  });

  it("read-only roles get no buttons", () => {
    expect(orderActionsFor(SUPPORT, "draft")).toEqual([]);
    expect(canReadOrders(SUPPORT) && !canWriteOrders(SUPPORT)).toBe(true);
  });

  it("navigation shows Orders only to staff who may read them", () => {
    const labels = (p: { permissions: string[] }, user_type: "staff" | "customer" = "staff") =>
      navigationFor({ ...p, user_type }).map((i) => i.label);
    expect(labels(AGENT)).toContain("Orders");
    expect(labels(me("lead:read:own"))).not.toContain("Orders");
    expect(labels(me("portal:order:read"), "customer")).toEqual([]);
  });
}); // prettier-ignore

describe("order input rules", () => {
  const line = { product_code: "", description: "Widget", quantity: "1", unit_price: "9.99", tax_rate: "19" };

  it("accepts a valid line and turns empty optional fields into null", () => {
    expect(orderLineSchema.parse(line).product_code).toBeNull();
  });

  it.each([
    [{ quantity: "0" }, "Quantity must be more than 0"],
    [{ unit_price: "1.999" }, "at most 2 decimals"],
    [{ unit_price: "-1" }, "at most 2 decimals"],
    [{ tax_rate: "120" }, "between 0 and 100"],
    [{ description: " " }, "Describe what is ordered."],
  ])("rejects %o", (change, message) => {
    const result = orderLineSchema.safeParse({ ...line, ...change });
    expect(result.success).toBe(false);
    expect(result.error?.issues[0].message).toContain(message);
  });

  it("checks the header", () => {
    expect(orderHeaderSchema.safeParse({ currency: "eur", customer_reference: "", expected_delivery_date: "", internal_note: "" }).success).toBe(false);
    expect(orderHeaderSchema.parse({ currency: "EUR", customer_reference: " ", expected_delivery_date: "", internal_note: "" }).customer_reference).toBeNull();
  });
}); // prettier-ignore

describe("order display helpers", () => {
  it("formats numbers, money and quantities", () => {
    expect(orderNumber(7)).toBe("SO-0007");
    expect(formatMoney("1234.5", "EUR")).toBe("€1,234.50");
    expect(formatMoney("0.10", "USD")).toBe("US$0.10");
    expect(formatQuantity("1.500")).toBe("1.5");
    expect(formatQuantity("3.000")).toBe("3");
  });

  it("uses customer wording in the portal", () => {
    const { rerender } = render(<OrderStatusBadge status="in_fulfilment" />);
    expect(screen.getByText("In fulfilment")).toBeInTheDocument();
    rerender(<OrderStatusBadge status="in_fulfilment" portal />);
    expect(screen.getByText("Being prepared")).toBeInTheDocument();
  });

  it("lists portal orders with links, totals and status", () => {
    render(
      <PortalOrderList
        emptyText="none"
        orders={[{ id: "o1", number: 3, account_id: "a", status: "shipped", currency: "EUR", customer_reference: "PO-9", total: "71.36", expected_delivery_date: null, confirmed_at: null }]}
      />,
    );
    expect(screen.getByRole("link", { name: /SO-0003/ })).toHaveAttribute("href", "/portal/orders/o1");
    expect(screen.getByText("€71.36")).toBeInTheDocument();
    expect(screen.getByText("On its way")).toBeInTheDocument();
  });

  it("marks progress up to the current step", () => {
    render(<OrderProgress order={{ status: "shipped", timeline: [{ status: "confirmed", at: "2026-10-18T08:00:00Z" }, { status: "shipped", at: "2026-10-19T08:00:00Z" }] }} />);
    const steps = within(screen.getByRole("list", { name: "Order progress" })).getAllByRole("listitem");
    expect(steps.map((s) => s.textContent?.startsWith("✓"))).toEqual([true, true, true, false]);
    expect(steps[2]).toHaveAttribute("aria-current", "step");
  });

  it("shows no progress for cancelled orders", () => {
    const { container } = render(<OrderProgress order={{ status: "cancelled", timeline: [] }} />);
    expect(container).toBeEmptyDOMElement();
  });
}); // prettier-ignore

vi.mock("next/navigation", () => ({ usePathname: () => "/orders/new" }));

describe("OrderForm", () => {
  type Action = (state: FormState, formData: FormData) => Promise<FormState>;
  const defaults = { currency: "EUR", customer_reference: "", expected_delivery_date: "", internal_note: "", lines: [] };

  it("previews line amounts and the total while typing, and can add and remove lines", async () => {
    const user = userEvent.setup();
    render(<OrderForm action={vi.fn<Action>()} initialState={initialFormState} accounts={[{ id: "a1", name: "Acme" }]} defaults={defaults} cancelHref="/orders" submitLabel="Save draft" />);

    const line1 = screen.getByRole("group", { name: "Line 1" });
    await user.clear(within(line1).getByLabelText("Quantity"));
    await user.type(within(line1).getByLabelText("Quantity"), "3");
    await user.type(within(line1).getByLabelText(/Unit price/), "19.99");
    await user.clear(within(line1).getByLabelText("Tax rate (%)"));
    await user.type(within(line1).getByLabelText("Tax rate (%)"), "19");
    expect(within(line1).getByText("€71.36")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Add line" }));
    expect(screen.getByRole("group", { name: "Line 2" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Remove line 2" }));
    expect(screen.queryByRole("group", { name: "Line 2" })).not.toBeInTheDocument();

    const preview = screen.getByLabelText("Order total preview");
    expect(within(preview).getAllByText("€71.36")).toHaveLength(1);
    expect(screen.getByText(/Customers never see this note/)).toBeInTheDocument();
  });

  it("sends repeated line fields to the Server Action and shows its errors per line", async () => {
    const action = vi.fn<Action>(async (state) => ({
      ...state,
      attempt: state.attempt + 1,
      fieldErrors: { "lines.0.unit_price": "Unit price: use a number with at most 2 decimals, e.g. 19.99." },
    }));
    const user = userEvent.setup();
    render(<OrderForm action={action} initialState={initialFormState} accounts={[{ id: "a1", name: "Acme" }]} defaults={defaults} cancelHref="/orders" submitLabel="Save draft" />);

    await user.type(screen.getByLabelText("Description"), "Widget");
    await user.type(screen.getByLabelText(/Unit price/), "1.999");
    await user.click(screen.getByRole("button", { name: "Save draft" }));

    const sent = action.mock.calls[0][1];
    expect(sent.get("account_id")).toBe("a1"); // only account offered is preselected
    expect(sent.getAll("line_description")).toEqual(["Widget"]);
    expect(sent.getAll("line_unit_price")).toEqual(["1.999"]);
    expect(await screen.findByText(/at most 2 decimals/)).toBeInTheDocument();
    expect(screen.getByLabelText(/Unit price/)).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByLabelText(/Unit price/)).toHaveValue("1.999"); // input kept
  });
}); // prettier-ignore
