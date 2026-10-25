import {
  logReceivedEmail,
  previewTemplate,
  sendEmail,
} from "@/app/(app)/communications/actions";
import { EmailComposer } from "@/components/email-composer";
import { EmailStatusBadge } from "@/components/email-views";
import { Card } from "@/components/ui";
import type {
  ContactPage,
  EmailPage,
  EmailTemplate,
  Me,
} from "@/lib/api-types";
import {
  blockedReason,
  failureText,
  recipientOptions,
  type EmailPerson,
  type EmailRecord,
} from "@/lib/communications";
import { formatDateTime } from "@/lib/format";
import { canReadEmailHistory, canSendEmails } from "@/lib/permissions";
import { apiFetch } from "@/lib/server/api";

const HISTORY_LIMIT = 20;

/**
 * E-mails of a lead, contact, account or deal (ADR 0012), with "Send e-mail" and "Log a
 * received e-mail". The API shows the history only to people who may read the record and
 * answers 404 otherwise - then the card is simply not shown.
 *
 * On a lead or contact page the e-mail is with that person (`person`); on an account or deal
 * page the user picks one of the account's contacts (`accountId`).
 */
export async function EmailCard({
  me,
  record,
  person,
  personLabel,
  accountId,
}: {
  me: Me;
  record: EmailRecord;
  person?: EmailPerson;
  personLabel?: string;
  accountId?: string | null;
}) {
  if (!canReadEmailHistory(me)) return null;
  const history = await apiFetch<EmailPage>(
    `/communications/history?${record.type === "opportunity" ? "opportunity" : record.type}_id=${record.id}&limit=${HISTORY_LIMIT}`,
  ).catch(() => null);
  if (!history) return null;

  const mayWrite = canSendEmails(me);
  const [templates, contacts] = mayWrite
    ? await Promise.all([
        apiFetch<EmailTemplate[]>("/communications/templates").catch(() => []),
        !person && accountId
          ? apiFetch<ContactPage>(`/contacts?account_id=${accountId}&limit=200`)
              .then((page) => page.items)
              .catch(() => [])
          : Promise.resolve([]),
      ])
    : [[], []];

  const fixed =
    person && personLabel
      ? {
          ...(record.type === "lead" ? { lead_id: record.id } : { contact_id: record.id }),
          label: person.email ? `${personLabel} <${person.email}>` : personLabel,
        }
      : undefined;
  const sendBlocked = person ? blockedReason(person, "send") : null;
  const logBlocked = person ? blockedReason(person, "log") : null;
  const send = sendEmail.bind(null, record);
  const log = logReceivedEmail.bind(null, record);

  return (
    <Card aria-labelledby={`emails-${record.id}`}>
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 px-5 py-4">
        <h2 id={`emails-${record.id}`} className="text-base font-semibold text-slate-900">E-mails</h2>
        {mayWrite && (
          <div className="flex flex-wrap gap-2">
            {!sendBlocked && (
              <EmailComposer mode="send" action={send} fixedRecipient={fixed} recipients={fixed ? undefined : recipientOptions(contacts, "send")}
                templates={templates.map((t) => ({ id: t.id, name: t.name }))} preview={previewTemplate} />
            )}
            {!logBlocked && (
              <EmailComposer mode="log" action={log} fixedRecipient={fixed} recipients={fixed ? undefined : recipientOptions(contacts, "log")} />
            )}
          </div>
        )}
      </div>
      {mayWrite && sendBlocked && (
        <p className="border-b border-slate-200 bg-slate-50 px-5 py-3 text-sm text-slate-700">
          {`E-mails can't be sent: ${sendBlocked}.`}{!logBlocked && " You can still log e-mails they send you."}
        </p>
      )}
      {history.items.length === 0 ? (
        <p className="px-5 py-6 text-sm text-slate-600">No e-mails yet.</p>
      ) : (
        <ul className="divide-y divide-slate-100">
          {history.items.map((m) => (
            <li key={m.id} className="px-5 py-3">
              <details>
                <summary className="flex cursor-pointer flex-wrap items-center gap-x-3 gap-y-1">
                  <span className="text-xs text-slate-500">{m.direction === "outbound" ? "To" : "From"} {m.to_address}</span>
                  <span className="text-sm font-medium text-slate-900">{m.subject}</span>
                  <EmailStatusBadge status={m.status} />
                  <span className="text-xs text-slate-500">
                    {formatDateTime(m.sent_at ?? m.created_at)}{m.sent_by_user_id === me.user_id && " · by you"}
                  </span>
                </summary>
                {m.status === "failed" && <p className="mt-2 text-sm text-red-700">{failureText(m.error_code)}</p>}
                <p className="mt-2 whitespace-pre-wrap break-words rounded-md bg-slate-50 p-3 text-sm text-slate-800">{m.body}</p>
              </details>
            </li>
          ))}
        </ul>
      )}
      {history.total > history.items.length && (
        <p className="border-t border-slate-200 px-5 py-3 text-xs text-slate-500">
          Showing the newest {history.items.length} of {history.total} e-mails.
        </p>
      )}
    </Card>
  ); // prettier-ignore
}
