import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import {
  InvoiceActionBar,
  ReversePaymentButton,
} from "@/app/(app)/invoices/[id]/invoice-action-bar";
import {
  BalanceSummary,
  PaymentStateBadge,
  PortalInvoiceList,
  creditNoteNumber,
  invoiceNumber,
} from "@/components/invoices";
import type { DialogState } from "@/lib/dialog-state";
import {
  canManageInvoices,
  canReadInvoices,
  canRecordPayments,
  navigationFor,
} from "@/lib/permissions";
import {
  creditNoteSchema,
  paymentSchema,
  reversalSchema,
} from "@/lib/validation/invoices";

/** Phase 13: invoices - display helpers, input checks, action bar. */

vi.mock("next/navigation", () => ({ usePathname: () => "/invoices" }));

type Bound = (state: DialogState, formData: FormData) => Promise<DialogState>;
const me = (...permissions: string[]) => ({ permissions });

describe("invoice display helpers", () => {
  it("numbers drafts honestly", () => {
    expect(invoiceNumber(null)).toBe("Draft invoice");
    expect(invoiceNumber(12)).toBe("INV-0012");
    expect(creditNoteNumber(3)).toBe("CN-0003");
  });

  it("uses customer wording in the portal", () => {
    const { rerender } = render(<PaymentStateBadge state="open" />);
    expect(screen.getByText("Open")).toBeInTheDocument();
    rerender(<PaymentStateBadge state="open" portal />);
    expect(screen.getByText("Awaiting payment")).toBeInTheDocument();
  });

  it("explains the balance", () => {
    render(<BalanceSummary currency="EUR" total="71.36" credited="1.36" paid="50.00" balance="20.00" />);
    const balance = screen.getByLabelText("Balance");
    expect(within(balance).getByText("Amount due").nextSibling).toHaveTextContent("€20.00");
    expect(within(balance).getByText("− €1.36")).toBeInTheDocument();
  });

  it("lists portal invoices with what is still due", () => {
    render(
      <PortalInvoiceList
        emptyText="none"
        invoices={[
          { id: "i1", number: 4, order_id: "o", account_id: "a", payment_state: "overdue", currency: "EUR", total: "71.36", balance_due: "20.00", issue_date: "2026-10-01", due_date: "2026-10-15" },
          { id: "i2", number: 5, order_id: "o", account_id: "a", payment_state: "paid", currency: "EUR", total: "10.00", balance_due: "0.00", issue_date: "2026-10-01", due_date: "2026-10-15" },
        ]}
      />,
    );
    expect(screen.getByRole("link", { name: "INV-0004" })).toHaveAttribute("href", "/portal/invoices/i1");
    expect(screen.getByText(/€20.00 due/)).toBeInTheDocument();
    expect(screen.getByText("Payment overdue")).toBeInTheDocument();
    expect(screen.getAllByText(/€[0-9.]+ due/)).toHaveLength(1); // nothing due on the paid one
  });
}); // prettier-ignore

describe("who sees invoice controls (display only)", () => {
  it("matches the role matrix", () => {
    const agent = me("invoice:read:own_accounts");
    const manager = me("invoice:read:all", "invoice:manage", "payment:record");
    expect(canReadInvoices(agent) && !canManageInvoices(agent) && !canRecordPayments(agent)).toBe(true);
    expect(canManageInvoices(manager) && canRecordPayments(manager)).toBe(true);
    expect(navigationFor({ ...agent, user_type: "staff" }).map((i) => i.label)).toContain("Invoices");
    expect(navigationFor({ permissions: ["portal:invoice:read"], user_type: "customer" })).toEqual([]);
  });
}); // prettier-ignore

describe("invoice input rules", () => {
  it("checks payments", () => {
    expect(paymentSchema.parse({ amount: "10", received_on: "2026-10-18", method: "cash", reference: " " }).reference).toBeNull();
    for (const amount of ["0", "-1", "1.001", "abc"])
      expect(paymentSchema.safeParse({ amount, received_on: "2026-10-18", method: "cash", reference: "" }).success).toBe(false);
    expect(paymentSchema.safeParse({ amount: "1", received_on: "", method: "cash", reference: "" }).success).toBe(false);
    expect(paymentSchema.safeParse({ amount: "1", received_on: "2026-10-18", method: "crypto", reference: "" }).success).toBe(false);
  });

  it("checks credit notes and reversals", () => {
    expect(creditNoteSchema.safeParse({ reason: "ok", description: "x", unit_price: "1", tax_rate: "0" }).success).toBe(false); // reason too short
    expect(creditNoteSchema.safeParse({ reason: "Damaged", description: "x", unit_price: "1", tax_rate: "101" }).success).toBe(false);
    expect(creditNoteSchema.safeParse({ reason: "Damaged", description: "x", unit_price: "1.5", tax_rate: "19" }).success).toBe(true);
    expect(reversalSchema.safeParse({ reason: "  " }).success).toBe(false);
  });
}); // prettier-ignore

describe("InvoiceActionBar", () => {
  const invoice = { number: 4, version: 3, currency: "EUR", balance: "20.00" };

  it("shows only the actions it was given", () => {
    const { rerender, container } = render(<InvoiceActionBar invoice={invoice} today="2026-10-18" defaultDueDate="2026-11-01" actions={{}} />);
    expect(container).toBeEmptyDOMElement();
    rerender(<InvoiceActionBar invoice={invoice} today="2026-10-18" defaultDueDate="2026-11-01" actions={{ pay: vi.fn<Bound>() }} />);
    const group = screen.getByRole("group", { name: "Invoice actions" });
    expect(within(group).getAllByRole("button").map((b) => b.textContent)).toEqual(["Record payment"]);
  });

  it("pre-fills the payment with the amount still owed and sends it after confirmation", async () => {
    const pay = vi.fn<Bound>(async (state) => state);
    const user = userEvent.setup();
    render(<InvoiceActionBar invoice={invoice} today="2026-10-18" defaultDueDate="2026-11-01" actions={{ pay }} />);

    await user.click(screen.getByRole("button", { name: "Record payment" }));
    const dialog = screen.getByRole("dialog", { name: "Record a payment for INV-0004" });
    expect(within(dialog).getByText("€20.00")).toBeInTheDocument();
    expect(within(dialog).getByLabelText(/Amount/)).toHaveValue("20.00");
    expect(within(dialog).getByLabelText("Received on")).toHaveAttribute("max", "2026-10-18");
    expect(pay).not.toHaveBeenCalled();
    await user.click(within(dialog).getByRole("button", { name: "Record payment" }));

    const sent = pay.mock.calls[0][1];
    expect([sent.get("amount"), sent.get("received_on"), sent.get("method")]).toEqual(["20.00", "2026-10-18", "bank_transfer"]);
  });

  it("issuing sends the version and due date", async () => {
    const issue = vi.fn<Bound>(async (state) => state);
    const user = userEvent.setup();
    render(<InvoiceActionBar invoice={{ ...invoice, number: null }} today="2026-10-18" defaultDueDate="2026-11-01" actions={{ issue }} />);

    await user.click(screen.getByRole("button", { name: "Issue invoice" }));
    await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Issue invoice" }));

    const sent = issue.mock.calls[0][1];
    expect([sent.get("version"), sent.get("due_date")]).toEqual(["3", "2026-11-01"]);
  });

  it("reversing a payment asks for confirmation and a reason", async () => {
    const reverse = vi.fn<Bound>(async (state) => ({ ...state, attempt: state.attempt + 1, fieldErrors: { reason: "Say why the payment is reversed (at least 3 characters)." } }));
    const user = userEvent.setup();
    render(<ReversePaymentButton amount="€50.00" action={reverse} />);

    await user.click(screen.getByRole("button", { name: "Reverse" }));
    await user.click(screen.getByRole("button", { name: "Reverse payment" }));
    expect(await screen.findByText(/Say why the payment is reversed/)).toBeInTheDocument();
  });
}); // prettier-ignore
