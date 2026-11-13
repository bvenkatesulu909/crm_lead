import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { createPaymentLink } from "@/app/(app)/invoices/payment-link-actions";
import {
  PortalPayByUpi,
  StaffPaymentLinks,
} from "@/components/payment-link-views";
import { ApiError } from "@/lib/api-error";
import { initialDialogState } from "@/lib/dialog-state";
import {
  canOfferUpi,
  openLink,
  paymentLinkErrorText,
  safePayUrl,
  type PaymentLink,
} from "@/lib/payment-links";

const apiFetch = vi.fn();
vi.mock("@/lib/server/api", () => ({
  apiFetch: (...a: unknown[]) => apiFetch(...a),
}));
vi.mock("next/navigation", () => ({
  redirect: (to: string) => {
    throw new Error(`REDIRECT:${to}`);
  },
}));

const INVOICE = "11111111-1111-4111-8111-111111111111";
const NOW = new Date("2026-11-13T09:00:00Z");

function link(over: Partial<PaymentLink> = {}): PaymentLink {
  return {
    id: "22222222-2222-4222-8222-222222222222",
    invoice_id: INVOICE,
    short_url: "https://rzp.io/i/abc123",
    amount: "214.16",
    currency: "INR",
    status: "created",
    expires_at: "2026-11-20T09:00:00Z",
    created_at: "2026-11-13T08:00:00Z",
    paid_at: null,
    ...over,
  };
}

function problem(status: number, code: string) {
  return new ApiError(status, {
    title: "x",
    status,
    detail: "Server words",
    code,
    request_id: "r",
  });
}

beforeEach(() => apiFetch.mockReset());

describe("helpers", () => {
  it("only plain https addresses are shown or opened", () => {
    expect(safePayUrl("https://rzp.io/i/abc")).toBe("https://rzp.io/i/abc");
    for (const bad of [
      "http://rzp.io/i/abc",
      "javascript:alert(1)",
      "data:text/html,x",
      "https://user:pw@rzp.io/i/abc",
      "//rzp.io/i/abc",
      "not a url",
      "",
    ])
      expect(safePayUrl(bad)).toBeNull();
  });

  it("the open link is the one that is created and not past its expiry", () => {
    const open = link();
    expect(openLink([open], NOW)).toBe(open);
    expect(openLink([link({ status: "paid" })], NOW)).toBeNull();
    expect(openLink([link({ status: "cancelled" })], NOW)).toBeNull();
    expect(
      openLink([link({ expires_at: "2026-11-13T08:59:59Z" })], NOW),
    ).toBeNull();
    expect(openLink([], NOW)).toBeNull();
  });

  it("UPI is offered only for an issued invoice in rupees with money owed", () => {
    const ok = { status: "issued", currency: "INR", balance_due: "10.00" };
    expect(canOfferUpi(ok)).toBe(true);
    expect(canOfferUpi({ ...ok, status: "draft" })).toBe(false);
    expect(canOfferUpi({ ...ok, currency: "EUR" })).toBe(false);
    expect(canOfferUpi({ ...ok, balance_due: "0.00" })).toBe(false);
  });

  it("known error codes become plain sentences, others keep the server's words", () => {
    expect(paymentLinkErrorText("payment_links_unavailable", "x")).toMatch(
      /switched off.*AI agents/,
    );
    expect(paymentLinkErrorText("payment_provider_unavailable", "x")).toMatch(
      /could not be reached/,
    );
    expect(paymentLinkErrorText("payment_link_rate_limited", "x")).toMatch(
      /Too many/,
    );
    expect(paymentLinkErrorText("invoice_not_payable", "Only issued")).toBe(
      "Only issued",
    );
    expect(paymentLinkErrorText(null, "fallback")).toBe("fallback");
  });
});

describe("createPaymentLink", () => {
  it("sends only the invoice id and goes back to the card", async () => {
    apiFetch.mockResolvedValue({});
    await expect(
      createPaymentLink(INVOICE, initialDialogState),
    ).rejects.toThrow(`REDIRECT:/invoices/${INVOICE}?done=link-created#upi`);
    expect(apiFetch).toHaveBeenCalledTimes(1);
    const [path, init] = apiFetch.mock.calls[0];
    expect(path).toBe("/payment-links");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual({ invoice_id: INVOICE });
  });

  it("refuses an id that is not an id before anything is sent", async () => {
    await expect(
      createPaymentLink("../x", initialDialogState),
    ).rejects.toThrow();
    expect(apiFetch).not.toHaveBeenCalled();
  });

  it("a refusal stays on the page with plain words and counts the attempt", async () => {
    apiFetch.mockRejectedValueOnce(problem(503, "payment_links_unavailable"));
    const result = await createPaymentLink(INVOICE, initialDialogState);
    expect(result.attempt).toBe(1);
    expect(result.error?.message).toMatch(/switched off/);
  });

  it("an unreachable payment service is explained", async () => {
    apiFetch.mockRejectedValueOnce(
      problem(503, "payment_provider_unavailable"),
    );
    const result = await createPaymentLink(INVOICE, initialDialogState);
    expect(result.error?.message).toMatch(/could not be reached/);
  });
});

describe("StaffPaymentLinks", () => {
  const noop = vi.fn();

  function show(links: PaymentLink[], canCreate = true) {
    return render(
      <StaffPaymentLinks
        links={links}
        currency="INR"
        canCreate={canCreate}
        action={noop}
        now={NOW}
      />,
    );
  }

  it("without a link it says so and offers to create one", () => {
    show([]);
    expect(screen.getByText("No payment link yet.")).toBeTruthy();
    expect(
      screen.getByRole("button", { name: "Create UPI payment link" }),
    ).toBeTruthy();
  });

  it("an open link shows its address as plain text, the amount and a safe link", () => {
    show([link()]);
    const box = screen.getByTestId("open-link");
    expect(box.textContent).toContain("₹214.16");
    expect(box.textContent).toContain("https://rzp.io/i/abc123");
    const open = screen.getByRole("link", { name: "Open payment page" });
    expect(open.getAttribute("href")).toBe("https://rzp.io/i/abc123");
    expect(open.getAttribute("target")).toBe("_blank");
    expect(open.getAttribute("rel")).toContain("noopener");
    expect(
      screen.getByRole("button", {
        name: "Create a new link (replaces this one)",
      }),
    ).toBeTruthy();
  });

  it("an address that is not https is never shown or opened", () => {
    show([link({ short_url: "javascript:alert(1)" })]);
    expect(
      screen.queryByRole("link", { name: "Open payment page" }),
    ).toBeNull();
    expect(screen.queryByText(/javascript/)).toBeNull();
    expect(screen.getByText("There is no open payment link.")).toBeTruthy();
  });

  it("an expired link is not offered as open and an earlier one is listed", () => {
    show([
      link({ expires_at: "2026-11-13T08:00:00Z" }),
      link({ id: "x", status: "paid", amount: "10.00" }),
    ]);
    expect(screen.queryByTestId("open-link")).toBeNull();
    expect(screen.getByText("Expired")).toBeTruthy();
    expect(screen.getByText("Paid")).toBeTruthy();
  });

  it("people who cannot collect payments see the link but no button", () => {
    show([link()], false);
    expect(screen.getByTestId("open-link")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Create/ })).toBeNull();
  });

  it("pressing the button asks the server and shows its refusal in words", async () => {
    const action = vi.fn().mockResolvedValue({
      attempt: 1,
      fieldErrors: {},
      error: {
        code: "payment_links_unavailable",
        message: "UPI payment links are switched off for your organisation.",
        fieldErrors: {},
        requestId: "req-1",
        status: 503,
      },
    });
    render(
      <StaffPaymentLinks
        links={[]}
        currency="INR"
        canCreate
        action={action}
        now={NOW}
      />,
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Create UPI payment link" }),
    );
    expect(action).toHaveBeenCalledTimes(1);
    expect((await screen.findByRole("alert")).textContent).toContain(
      "switched off",
    );
  });

  it("says the CRM never sees the buyer's UPI details", () => {
    show([]);
    expect(screen.getByText(/never sees their UPI details/)).toBeTruthy();
  });
});

describe("PortalPayByUpi", () => {
  it("a customer gets one button to the open link and an honest note", () => {
    render(<PortalPayByUpi link={link()} />);
    expect(screen.getByRole("note").textContent).toContain("₹214.16");
    expect(screen.getByRole("note").textContent).toContain(
      "we never see your UPI details",
    );
    expect(
      screen.getByRole("link", { name: "Pay by UPI" }).getAttribute("href"),
    ).toBe("https://rzp.io/i/abc123");
  });

  it("nothing is shown for an address that is not https", () => {
    const { container } = render(
      <PortalPayByUpi link={link({ short_url: "http://rzp.io/i/abc" })} />,
    );
    expect(container.textContent).toBe("");
  });
});
