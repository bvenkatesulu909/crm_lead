"use server";

import { redirect } from "next/navigation";

import { toErrorInfo } from "@/lib/api-error";
import type { EmailTemplate, TemplatePreview } from "@/lib/api-types";
import {
  checkMessage,
  checkTemplate,
  isUuid,
  recordPath,
  type EmailRecord,
} from "@/lib/communications";
import type { DialogState } from "@/lib/dialog-state";
import type { FormState } from "@/lib/form-state";
import { apiFetch } from "@/lib/server/api";

/**
 * Communication Center Server Actions (ADR 0012). Every ID from the browser is untrusted: the
 * API loads the lead or contact under its own read rules (404 if not allowed) and takes the
 * e-mail address from that record - the browser never sends an address.
 */

const failed = (
  previous: DialogState,
  fieldErrors: Record<string, string>,
): DialogState => ({ attempt: previous.attempt + 1, fieldErrors, error: null });

function apiFailed(previous: DialogState, error: unknown): DialogState {
  const info = toErrorInfo(error);
  return { attempt: previous.attempt + 1, fieldErrors: info.fieldErrors, error: info };
}

/**
 * Who the e-mail is with, from the record the card sits on: a lead or contact page writes to
 * that record; an account or deal page writes to one of its contacts and files it there.
 */
function recipientOf(
  record: EmailRecord,
  formData: FormData,
): Record<string, string> | { error: string } {
  if (record.type === "lead") return { lead_id: record.id };
  if (record.type === "contact") return { contact_id: record.id };
  const contactId = String(formData.get("contact_id") ?? "");
  if (!isUuid(contactId)) return { error: "Choose a contact." };
  return record.type === "account"
    ? { contact_id: contactId, account_id: record.id }
    : { contact_id: contactId, opportunity_id: record.id };
}

async function submitMessage(
  record: EmailRecord,
  path: "/communications/emails" | "/communications/emails/received",
  previous: DialogState,
  formData: FormData,
): Promise<DialogState> {
  const back = recordPath(record); // throws for a tampered record type or id
  const recipient = recipientOf(record, formData);
  const message = checkMessage({
    subject: String(formData.get("subject") ?? ""),
    body: String(formData.get("body") ?? ""),
  });
  const fieldErrors = {
    ...("error" in recipient ? { contact_id: recipient.error } : {}),
    ...(message.ok ? {} : message.fieldErrors),
  };
  if ("error" in recipient || !message.ok) return failed(previous, fieldErrors);

  const templateId = String(formData.get("template_id") ?? "");
  const body: Record<string, string> = { ...recipient, ...message.data };
  if (path === "/communications/emails" && isUuid(templateId))
    body.template_id = templateId;
  try {
    await apiFetch(path, { method: "POST", body: JSON.stringify(body) });
  } catch (error) {
    return apiFailed(previous, error);
  }
  const done = path === "/communications/emails" ? "email-sent" : "email-logged";
  redirect(`${back}?done=${done}`);
}

export async function sendEmail(
  record: EmailRecord,
  previous: DialogState,
  formData: FormData,
): Promise<DialogState> {
  return submitMessage(record, "/communications/emails", previous, formData);
}

export async function logReceivedEmail(
  record: EmailRecord,
  previous: DialogState,
  formData: FormData,
): Promise<DialogState> {
  return submitMessage(record, "/communications/emails/received", previous, formData);
}

export type PreviewResult =
  | { ok: true; preview: TemplatePreview }
  | { ok: false; message: string };

/** The template filled in for the lead or contact (the API checks both may be read). */
export async function previewTemplate(
  templateId: string,
  recipient: { lead_id?: string; contact_id?: string },
): Promise<PreviewResult> {
  const leadId = recipient.lead_id ?? "";
  const contactId = recipient.contact_id ?? "";
  if (!isUuid(templateId) || (leadId && !isUuid(leadId)) || (contactId && !isUuid(contactId)))
    return { ok: false, message: "This template can't be used here." };
  const body = leadId ? { lead_id: leadId } : contactId ? { contact_id: contactId } : {};
  try {
    const preview = await apiFetch<TemplatePreview>(
      `/communications/templates/${templateId}/preview`,
      { method: "POST", body: JSON.stringify(body) },
    );
    return { ok: true, preview };
  } catch (error) {
    return { ok: false, message: toErrorInfo(error).message };
  }
}

// --- templates (managers) -------------------------------------------------------------------

function templateValues(formData: FormData) {
  return {
    name: String(formData.get("name") ?? ""),
    subject: String(formData.get("subject") ?? ""),
    body: String(formData.get("body") ?? ""),
  };
}

export async function createTemplate(
  previous: FormState,
  formData: FormData,
): Promise<FormState> {
  const values = templateValues(formData);
  const attempt = previous.attempt + 1;
  const checked = checkTemplate(values);
  if (!checked.ok) return { attempt, values, fieldErrors: checked.fieldErrors, error: null };
  try {
    await apiFetch<EmailTemplate>("/communications/templates", {
      method: "POST",
      body: JSON.stringify(checked.data),
    });
  } catch (error) {
    const info = toErrorInfo(error);
    return { attempt, values, fieldErrors: info.fieldErrors, error: info };
  }
  redirect("/communications/templates?done=created");
}

function templatePath(id: string) {
  if (!isUuid(id)) throw new Error("invalid template id");
  return `/communications/templates/${id}`;
}

function checkedVersion(version: number) {
  if (!Number.isInteger(version) || version < 1) throw new Error("invalid version");
  return version;
}

export async function updateTemplate(
  templateId: string,
  version: number,
  previous: FormState,
  formData: FormData,
): Promise<FormState> {
  const path = templatePath(templateId);
  const values = templateValues(formData);
  const attempt = previous.attempt + 1;
  const checked = checkTemplate(values);
  if (!checked.ok) return { attempt, values, fieldErrors: checked.fieldErrors, error: null };
  try {
    await apiFetch<EmailTemplate>(path, {
      method: "PATCH",
      body: JSON.stringify({ version: checkedVersion(version), ...checked.data }),
    });
  } catch (error) {
    const info = toErrorInfo(error);
    return { attempt, values, fieldErrors: info.fieldErrors, error: info };
  }
  redirect("/communications/templates?done=updated");
}

/** Deactivate (hide from agents) or reactivate a template. */
export async function setTemplateActive(
  templateId: string,
  version: number,
  active: boolean,
  previous: DialogState,
): Promise<DialogState> {
  const path = templatePath(templateId);
  try {
    await apiFetch<EmailTemplate>(path, {
      method: "PATCH",
      body: JSON.stringify({ version: checkedVersion(version), is_active: active }),
    });
  } catch (error) {
    return apiFailed(previous, error);
  }
  redirect(`/communications/templates?done=${active ? "reactivated" : "deactivated"}`);
}
