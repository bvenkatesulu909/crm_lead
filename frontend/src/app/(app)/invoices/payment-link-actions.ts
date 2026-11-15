"use server";

import { redirect } from "next/navigation";

import { toErrorInfo } from "@/lib/api-error";
import type { DialogState } from "@/lib/dialog-state";
import { paymentLinkErrorText } from "@/lib/payment-links";
import { apiFetch } from "@/lib/server/api";

/**
 * Create a UPI payment link for an invoice (ADR 0031). Only the invoice id is sent: the amount,
 * the reference and the expiry are decided by the API, which also decides who may do this.
 */
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export async function createPaymentLink(
  invoiceId: string,
  previous: DialogState,
): Promise<DialogState> {
  if (!UUID.test(invoiceId)) throw new Error("invalid invoice id");
  try {
    await apiFetch("/payment-links", {
      method: "POST",
      body: JSON.stringify({ invoice_id: invoiceId }),
    });
  } catch (error) {
    const info = toErrorInfo(error);
    return {
      attempt: previous.attempt + 1,
      fieldErrors: info.fieldErrors,
      error: {
        ...info,
        message: paymentLinkErrorText(info.code, info.message),
      },
    };
  }
  redirect(`/invoices/${invoiceId}?done=link-created#upi`);
}
