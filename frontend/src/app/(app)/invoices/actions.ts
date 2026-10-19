"use server";

import { redirect } from "next/navigation";
import type { z } from "zod";

import { toErrorInfo } from "@/lib/api-error";
import type { Invoice } from "@/lib/api-types";
import type { DialogState } from "@/lib/dialog-state";
import { apiFetch } from "@/lib/server/api";
import {
  creditNoteSchema,
  issueSchema,
  paymentSchema,
  reversalSchema,
} from "@/lib/validation/invoices";

/**
 * Invoice Server Actions. IDs, versions and amounts come from the browser and are untrusted:
 * the API decides who may do what, copies invoice lines from the order and calculates every
 * amount itself. No permission logic here.
 */
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const checkId = (id: string, what: string) => {
  if (!UUID.test(id)) throw new Error(`invalid ${what} id`);
  return id;
};
const invoicePath = (id: string) => `/invoices/${checkId(id, "invoice")}`;
const text = (formData: FormData, name: string) =>
  String(formData.get(name) ?? "");

function invalid(previous: DialogState, error: z.ZodError): DialogState {
  const fieldErrors: Record<string, string> = {};
  for (const issue of error.issues)
    fieldErrors[String(issue.path[0])] ??= issue.message;
  return { attempt: previous.attempt + 1, fieldErrors, error: null };
}

function failed(previous: DialogState, error: unknown): DialogState {
  const info = toErrorInfo(error);
  return {
    attempt: previous.attempt + 1,
    fieldErrors: info.fieldErrors,
    error: info,
  };
}

export async function createInvoiceFromOrder(
  orderId: string,
  previous: DialogState,
): Promise<DialogState> {
  let invoice: Invoice;
  try {
    invoice = await apiFetch<Invoice>("/invoices", {
      method: "POST",
      body: JSON.stringify({ order_id: checkId(orderId, "order") }),
    });
  } catch (error) {
    return failed(previous, error);
  }
  redirect(`/invoices/${invoice.id}?done=created`);
}

export async function issueInvoice(
  invoiceId: string,
  previous: DialogState,
  formData: FormData,
): Promise<DialogState> {
  const path = invoicePath(invoiceId);
  const parsed = issueSchema.safeParse({
    due_date: text(formData, "due_date"),
  });
  if (!parsed.success) return invalid(previous, parsed.error);
  try {
    await apiFetch(`${path}/issue`, {
      method: "POST",
      body: JSON.stringify({
        version: Number(text(formData, "version")),
        due_date: parsed.data.due_date,
      }),
    });
  } catch (error) {
    return failed(previous, error);
  }
  redirect(`${path}?done=issued`);
}

export async function discardInvoice(
  invoiceId: string,
  previous: DialogState,
  formData: FormData,
): Promise<DialogState> {
  const path = invoicePath(invoiceId);
  try {
    await apiFetch(`${path}/discard`, {
      method: "POST",
      body: JSON.stringify({ version: Number(text(formData, "version")) }),
    });
  } catch (error) {
    return failed(previous, error);
  }
  redirect(`${path}?done=discarded`);
}

export async function recordPayment(
  invoiceId: string,
  previous: DialogState,
  formData: FormData,
): Promise<DialogState> {
  const path = invoicePath(invoiceId);
  const parsed = paymentSchema.safeParse({
    amount: text(formData, "amount"),
    received_on: text(formData, "received_on"),
    method: text(formData, "method"),
    reference: text(formData, "reference"),
  });
  if (!parsed.success) return invalid(previous, parsed.error);
  try {
    await apiFetch(`${path}/payments`, {
      method: "POST",
      body: JSON.stringify(parsed.data),
    });
  } catch (error) {
    return failed(previous, error);
  }
  redirect(`${path}?done=paid`);
}

export async function reversePayment(
  invoiceId: string,
  paymentId: string,
  previous: DialogState,
  formData: FormData,
): Promise<DialogState> {
  const path = invoicePath(invoiceId);
  const parsed = reversalSchema.safeParse({ reason: text(formData, "reason") });
  if (!parsed.success) return invalid(previous, parsed.error);
  try {
    await apiFetch(
      `${path}/payments/${checkId(paymentId, "payment")}/reverse`,
      {
        method: "POST",
        body: JSON.stringify(parsed.data),
      },
    );
  } catch (error) {
    return failed(previous, error);
  }
  redirect(`${path}?done=reversed`);
}

export async function issueCreditNote(
  invoiceId: string,
  previous: DialogState,
  formData: FormData,
): Promise<DialogState> {
  const path = invoicePath(invoiceId);
  const parsed = creditNoteSchema.safeParse({
    reason: text(formData, "reason"),
    description: text(formData, "description"),
    unit_price: text(formData, "unit_price"),
    tax_rate: text(formData, "tax_rate") || "0",
  });
  if (!parsed.success) return invalid(previous, parsed.error);
  const { reason, ...line } = parsed.data;
  try {
    await apiFetch(`${path}/credit-notes`, {
      method: "POST",
      body: JSON.stringify({ reason, lines: [{ ...line, quantity: "1" }] }),
    });
  } catch (error) {
    return failed(previous, error);
  }
  redirect(`${path}?done=credited`);
}
