/**
 * UPI payment links on invoices (ADR 0031, UP3): the shape the API returns and the few rules the
 * screens need. The amount, the address and the status all come from the server; nothing here
 * decides who may pay or how much. The address is Razorpay's, so it is only ever shown or opened
 * when it is a plain https address.
 */

export type PaymentLink = {
  id: string;
  invoice_id: string;
  short_url: string;
  amount: string;
  currency: string;
  status: "created" | "paid" | "cancelled" | "expired";
  expires_at: string;
  created_at: string;
  paid_at: string | null;
};

export const LINK_STATUS_TEXT: Record<PaymentLink["status"], string> = {
  created: "Open - waiting for the buyer to pay",
  paid: "Paid",
  cancelled: "Replaced by a newer link",
  expired: "Expired",
};

/** The address of a link, only if it is an https address; anything else is not shown or opened. */
export function safePayUrl(value: string): string | null {
  try {
    const url = new URL(value);
    return url.protocol === "https:" && !url.username && !url.password
      ? url.toString()
      : null;
  } catch {
    return null;
  }
}

/** The one link a buyer can still pay: open and not past its expiry. */
export function openLink(links: PaymentLink[], now: Date): PaymentLink | null {
  const open = links.find(
    (link) =>
      link.status === "created" &&
      new Date(link.expires_at).getTime() > now.getTime(),
  );
  return open ?? null;
}

/** Only an issued invoice in rupees with money still owed can be paid by UPI. */
export function canOfferUpi(invoice: {
  status: string;
  currency: string;
  balance_due: string;
}): boolean {
  return (
    invoice.status === "issued" &&
    invoice.currency === "INR" &&
    Number(invoice.balance_due) > 0
  );
}

export function paymentLinkErrorText(
  code: string | null,
  fallback: string,
): string {
  switch (code) {
    case "payment_links_unavailable":
      return "UPI payment links are switched off for your organisation. An administrator can switch them on under Automation → AI agents.";
    case "payment_provider_unavailable":
      return "The payment service could not be reached. Try again in a moment.";
    case "payment_link_rate_limited":
      return "Too many payment links were created. Try again later.";
    case "invoice_not_found":
      return "That invoice was not found.";
    case "forbidden":
      return "You may view this invoice but not collect payments for it.";
    default:
      return fallback;
  }
}
