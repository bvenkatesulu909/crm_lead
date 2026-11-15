import { createPaymentLink } from "@/app/(app)/invoices/payment-link-actions";
import { StaffPaymentLinks } from "@/components/payment-link-views";
import { Card } from "@/components/ui";
import { canOfferUpi, type PaymentLink } from "@/lib/payment-links";
import { apiFetch } from "@/lib/server/api";

/**
 * UPI payment links of one invoice (ADR 0031). Information and one button: the invoice page works
 * without it. Shown to people who can collect payments, and to others only when a link exists.
 */
export async function PaymentLinkCard({
  invoice,
  canCollect,
}: {
  invoice: {
    id: string;
    status: string;
    currency: string;
    balance_due: string;
  };
  canCollect: boolean;
}) {
  if (invoice.status !== "issued") return null;
  const data = await apiFetch<{ items: PaymentLink[] }>(
    `/payment-links?invoice_id=${invoice.id}`,
  ).catch(() => null);
  const links = data?.items ?? [];
  const offer = canOfferUpi(invoice);
  if (links.length === 0 && !(canCollect && offer)) return null;
  return (
    <Card id="upi" aria-labelledby="upi-heading">
      <h2
        id="upi-heading"
        className="border-b border-slate-200 px-5 py-4 text-base font-semibold text-slate-900"
      >
        Pay by UPI
      </h2>
      <div className="px-5 py-4">
        <StaffPaymentLinks
          links={links}
          currency={invoice.currency}
          canCreate={canCollect && offer}
          action={createPaymentLink.bind(null, invoice.id)}
          now={new Date()}
        />
      </div>
    </Card>
  );
}
