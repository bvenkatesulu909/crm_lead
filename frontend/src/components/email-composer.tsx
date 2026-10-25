"use client";

import {
  useActionState,
  useEffect,
  useId,
  useRef,
  useState,
  useTransition,
} from "react";

import { DialogField } from "@/components/action-dialog";
import { ErrorAlert, buttonClass, cx } from "@/components/ui";
import type { PreviewResult } from "@/app/(app)/communications/actions";
import type { DialogState } from "@/lib/dialog-state";
import { initialDialogState } from "@/lib/dialog-state";

/** A contact the e-mail could go to (account and deal pages); `blocked` explains why not. */
export type RecipientOption = { id: string; label: string; blocked?: string };
export type TemplateOption = { id: string; name: string };

type Action = (state: DialogState, formData: FormData) => Promise<DialogState>;
type Preview = (
  templateId: string,
  recipient: { lead_id?: string; contact_id?: string },
) => Promise<PreviewResult>;

/**
 * Write an e-mail ("send") or note one the customer sent us ("log"). The e-mail address is
 * never typed here: the API takes it from the lead or contact. Choosing a template fills in
 * the subject and text for this person (the API's preview); the text can still be edited, and
 * what is finally sent is exactly what the box shows. Subject and text stay as typed when the
 * server reports a problem.
 */
export function EmailComposer({
  mode,
  action,
  fixedRecipient,
  recipients,
  templates = [],
  preview,
}: {
  mode: "send" | "log";
  action: Action;
  /** The lead or contact of the page; absent on account and deal pages. */
  fixedRecipient?: { lead_id?: string; contact_id?: string; label: string };
  /** Contacts to choose from on account and deal pages. */
  recipients?: RecipientOption[];
  templates?: TemplateOption[];
  preview?: Preview;
}) {
  const [state, formAction, pending] = useActionState(action, initialDialogState);
  const dialog = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  // The form is built when the dialog is first opened (and then kept, so typed text survives
  // a server error): a record page then has no hidden extra "Subject" or "Text" fields.
  const [opened, setOpened] = useState(false);
  const [contactId, setContactId] = useState("");
  const [templateId, setTemplateId] = useState("");
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [note, setNote] = useState<{ kind: "info" | "error"; text: string } | null>(null);
  const [previewing, startPreview] = useTransition();
  const sending = mode === "send";
  const e = state.fieldErrors;

  // Keep the dialog open to show errors returned by the server.
  useEffect(() => {
    if (state.attempt > 0 && dialog.current && !dialog.current.open) dialog.current.showModal();
  }, [state.attempt]);

  const recipientForPreview = () =>
    fixedRecipient
      ? { lead_id: fixedRecipient.lead_id, contact_id: fixedRecipient.contact_id }
      : contactId
        ? { contact_id: contactId }
        : null;

  function applyTemplate(id: string) {
    setTemplateId(id);
    setNote(null);
    if (!id || !preview) return;
    const recipient = recipientForPreview();
    if (!recipient) {
      setNote({ kind: "error", text: "Choose who the e-mail is to first." });
      setTemplateId("");
      return;
    }
    startPreview(async () => {
      const result = await preview(id, recipient);
      if (!result.ok) {
        setNote({ kind: "error", text: result.message });
        return;
      }
      setSubject(result.preview.subject);
      setBody(result.preview.body);
      setNote(
        result.preview.missing.length
          ? { kind: "info", text: `Left empty (no value): ${result.preview.missing.join(", ")}. Check the text before sending.` }
          : { kind: "info", text: "The template was filled in. You can still change the text." },
      );
    });
  }

  const usable = recipients?.filter((r) => !r.blocked) ?? [];

  return (
    <>
      <button type="button" className={buttonClass(sending ? "primary" : "secondary")} onClick={() => { setOpened(true); dialog.current?.showModal(); }}>
        {sending ? "Send e-mail" : "Log a received e-mail"}
      </button>
      <dialog ref={dialog} aria-labelledby={titleId} className="m-auto w-[calc(100%-2rem)] max-w-2xl rounded-xl p-0 shadow-xl backdrop:bg-slate-900/50">
        {opened && <form action={formAction} noValidate className="space-y-5 p-6">
          <div>
            <h2 id={titleId} className="text-lg font-semibold text-slate-900">
              {sending ? "Send an e-mail" : "Log a received e-mail"}
            </h2>
            <p className="mt-2 text-sm text-slate-600">
              {sending
                ? "It is sent from the CRM in the background; replies come to your own e-mail address."
                : "Paste an e-mail the customer sent you, so it is kept in the history. Nothing is sent."}
            </p>
          </div>
          {state.error && <ErrorAlert title={sending ? "The e-mail could not be sent" : "The e-mail could not be saved"} error={state.error} />}

          {fixedRecipient ? (
            <p className="text-sm text-slate-700">
              <span className="font-medium">{sending ? "To:" : "From:"}</span> {fixedRecipient.label}
            </p>
          ) : (
            <DialogField id={`${titleId}-contact`} label={sending ? "To" : "From"} error={e.contact_id}
              hint={usable.length === 0 ? "None of the contacts here can be e-mailed (no address or no consent)." : undefined}>
              {(p) => (
                <select name="contact_id" value={contactId} onChange={(ev) => setContactId(ev.target.value)} {...p}>
                  <option value="">Choose a contact</option>
                  {recipients?.map((r) => (
                    <option key={r.id} value={r.id} disabled={Boolean(r.blocked)}>
                      {r.blocked ? `${r.label} (${r.blocked})` : r.label}
                    </option>
                  ))}
                </select>
              )}
            </DialogField>
          )}

          {sending && templates.length > 0 && (
            <DialogField id={`${titleId}-template`} label="Start from a template" optional>
              {(p) => (
                <select value={templateId} onChange={(ev) => applyTemplate(ev.target.value)} disabled={previewing} {...p}>
                  <option value="">No template</option>
                  {templates.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
                </select>
              )}
            </DialogField>
          )}
          <input type="hidden" name="template_id" value={templateId} />
          {previewing && <p className="text-sm text-slate-600" role="status">Filling in the template…</p>}
          {note && (
            <p role={note.kind === "error" ? "alert" : "status"}
              className={cx("rounded-md p-3 text-sm", note.kind === "error" ? "bg-red-50 text-red-800" : "bg-slate-50 text-slate-700")}>
              {note.text}
            </p>
          )}

          <DialogField id={`${titleId}-subject`} label="Subject" error={e.subject}>
            {(p) => <input name="subject" maxLength={200} value={subject} onChange={(ev) => setSubject(ev.target.value)} {...p} />}
          </DialogField>
          <DialogField id={`${titleId}-body`} label="Text" error={e.body} hint="Plain text. Line breaks are kept.">
            {(p) => <textarea name="body" rows={10} maxLength={50000} value={body} onChange={(ev) => setBody(ev.target.value)} {...p} />}
          </DialogField>

          <div className="flex justify-end gap-3 border-t border-slate-200 pt-4">
            <button type="button" className={buttonClass("secondary")} onClick={() => dialog.current?.close()}>Cancel</button>
            <button type="submit" disabled={pending || previewing} className={cx(buttonClass("primary"), (pending || previewing) && "opacity-70")}>
              {pending ? "Working…" : sending ? "Send" : "Save"}
            </button>
          </div>
        </form>}
      </dialog>
    </>
  ); // prettier-ignore
}
