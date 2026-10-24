"use server";

import { redirect } from "next/navigation";

import { ApiError, toErrorInfo } from "@/lib/api-error";
import type { Order } from "@/lib/api-types";
import type { DialogState } from "@/lib/dialog-state";
import type { FormState } from "@/lib/form-state";
import { apiFetch } from "@/lib/server/api";
import {
  MAX_LINES,
  orderHeaderSchema,
  orderLineSchema,
  type OrderLineInput,
} from "@/lib/validation/orders";

/**
 * Staff order Server Actions. IDs, versions and amounts come from the browser and are
 * untrusted: the API decides who may change which order and calculates every amount itself.
 * No permission logic here.
 */
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const orderPath = (id: string) => {
  if (!UUID.test(id)) throw new Error("invalid order id");
  return `/orders/${id}`;
};
const TARGETS = new Set([
  "confirmed",
  "in_fulfilment",
  "shipped",
  "delivered",
  "cancelled",
]);

const text = (formData: FormData, name: string) =>
  String(formData.get(name) ?? "");
const all = (formData: FormData, name: string) =>
  formData.getAll(name).map((v) => String(v));

type Parsed =
  | { ok: true; body: Record<string, unknown> }
  | {
      ok: false;
      values: Record<string, string>;
      fieldErrors: Record<string, string>;
    };

/** Reads the header fields and the repeated line inputs (in page order). */
function parseOrderForm(formData: FormData): Parsed {
  const header = {
    currency: text(formData, "currency"),
    customer_reference: text(formData, "customer_reference"),
    expected_delivery_date: text(formData, "expected_delivery_date"),
    internal_note: text(formData, "internal_note"),
  };
  const descriptions = all(formData, "line_description");
  const raw = descriptions.map((description, i) => ({
    product_code: all(formData, "line_product_code")[i] ?? "",
    description,
    quantity: all(formData, "line_quantity")[i] ?? "",
    unit_price: all(formData, "line_unit_price")[i] ?? "",
    tax_rate: all(formData, "line_tax_rate")[i] ?? "",
  }));
  const values = {
    ...header,
    account_id: text(formData, "account_id"),
    lines_json: JSON.stringify(raw),
  };
  const fieldErrors: Record<string, string> = {};

  const parsedHeader = orderHeaderSchema.safeParse(header);
  if (!parsedHeader.success)
    for (const issue of parsedHeader.error.issues)
      fieldErrors[String(issue.path[0])] ??= issue.message;
  if (raw.length > MAX_LINES)
    fieldErrors.lines = `An order can have at most ${MAX_LINES} lines.`;
  const lines: OrderLineInput[] = [];
  raw.forEach((line, i) => {
    const parsed = orderLineSchema.safeParse(line);
    if (parsed.success) lines.push(parsed.data);
    else
      for (const issue of parsed.error.issues)
        fieldErrors[`lines.${i}.${String(issue.path[0])}`] ??= issue.message;
  });

  if (Object.keys(fieldErrors).length > 0 || !parsedHeader.success)
    return { ok: false, values, fieldErrors };
  return { ok: true, body: { ...parsedHeader.data, lines } };
}

/** API validation errors -> form fields; line errors keep their line number. */
function apiFieldErrors(error: unknown): Record<string, string> {
  const fieldErrors: Record<string, string> = {};
  if (!(error instanceof ApiError)) return fieldErrors;
  for (const item of error.problem.errors ?? []) {
    const path = item.location.slice(1).map(String); // drop "body"
    const key =
      path[0] === "lines" && path.length >= 3
        ? `lines.${path[1]}.${path[2]}`
        : (path[0] ?? "form");
    fieldErrors[key] ??= item.message.replace(/^Value error, /, "");
  }
  return fieldErrors;
}

function failedForm(
  attempt: number,
  values: Record<string, string>,
  error: unknown,
): FormState {
  return {
    attempt,
    values,
    fieldErrors: apiFieldErrors(error),
    error: toErrorInfo(error),
  };
}

export async function createOrder(
  previous: FormState,
  formData: FormData,
): Promise<FormState> {
  const attempt = previous.attempt + 1;
  const accountId = text(formData, "account_id");
  // The name of the chosen account only lets the form show it again after an error.
  const accountLabel = text(formData, "account_label");
  const parsed = parseOrderForm(formData);
  if (!UUID.test(accountId)) {
    const fieldErrors = parsed.ok ? {} : parsed.fieldErrors;
    return {
      attempt,
      values: {
        ...(parsed.ok ? { account_id: accountId } : parsed.values),
        account_label: accountLabel,
      },
      fieldErrors: {
        ...fieldErrors,
        account_id: "Choose the customer account.",
      },
      error: null,
    };
  }
  if (!parsed.ok)
    return {
      attempt,
      values: { ...parsed.values, account_label: accountLabel },
      fieldErrors: parsed.fieldErrors,
      error: null,
    };
  let order: Order;
  try {
    order = await apiFetch<Order>("/orders", {
      method: "POST",
      body: JSON.stringify({ account_id: accountId, ...parsed.body }),
    });
  } catch (error) {
    return failedForm(
      attempt,
      { account_id: accountId, account_label: accountLabel },
      error,
    );
  }
  redirect(`/orders/${order.id}?done=created`);
}

export async function updateOrder(
  orderId: string,
  previous: FormState,
  formData: FormData,
): Promise<FormState> {
  const path = orderPath(orderId);
  const attempt = previous.attempt + 1;
  const parsed = parseOrderForm(formData);
  if (!parsed.ok)
    return {
      attempt,
      values: parsed.values,
      fieldErrors: parsed.fieldErrors,
      error: null,
    };
  try {
    await apiFetch(path, {
      method: "PUT",
      body: JSON.stringify({
        version: Number(text(formData, "version")),
        ...parsed.body,
      }),
    });
  } catch (error) {
    return failedForm(attempt, {}, error);
  }
  redirect(`${path}?done=updated`);
}

/** The fields each status change accepts (the API rejects the others). */
function statusBody(target: string, formData: FormData) {
  const body: Record<string, unknown> = {
    status: target,
    version: Number(text(formData, "version")),
  };
  const note = text(formData, "note").trim();
  if (note) body.note = note;
  if (target === "cancelled") body.reason = text(formData, "reason").trim();
  if (target === "shipped") {
    const tracking = text(formData, "tracking_reference").trim();
    if (tracking) body.tracking_reference = tracking;
  }
  if (["confirmed", "in_fulfilment", "shipped"].includes(target)) {
    const date = text(formData, "expected_delivery_date").trim();
    if (date) body.expected_delivery_date = date;
  }
  return body;
}

export async function changeOrderStatus(
  orderId: string,
  target: string,
  previous: DialogState,
  formData: FormData,
): Promise<DialogState> {
  const path = orderPath(orderId);
  if (!TARGETS.has(target)) throw new Error("invalid status");
  const body = statusBody(target, formData);
  const fieldErrors: Record<string, string> = {};
  if (target === "cancelled" && String(body.reason).length < 3)
    fieldErrors.reason =
      "Please tell the customer why (at least 3 characters).";
  if (String(body.reason ?? "").length > 500)
    fieldErrors.reason = "Reason can be at most 500 characters.";
  if (String(body.note ?? "").length > 2000)
    fieldErrors.note = "Note can be at most 2000 characters.";
  if (Object.keys(fieldErrors).length > 0)
    return { attempt: previous.attempt + 1, fieldErrors, error: null };
  try {
    await apiFetch(`${path}/status`, {
      method: "POST",
      body: JSON.stringify(body),
    });
  } catch (error) {
    const info = toErrorInfo(error);
    return {
      attempt: previous.attempt + 1,
      fieldErrors: info.fieldErrors,
      error: info,
    };
  }
  redirect(`${path}?done=${target}`);
}
