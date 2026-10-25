import { Card, cx } from "@/components/ui";
import type { PublicChatTranscript } from "@/lib/api-types";
import { formatDateTime } from "@/lib/format";

/**
 * The website chat that created a lead (ADR 0013), for staff on the lead page. The visitor's
 * words are shown as plain text (React escapes them), never as HTML. Leads that came another
 * way have no conversation, and the card is left out.
 */
export function ChatTranscriptCard({
  transcript,
}: {
  transcript: PublicChatTranscript;
}) {
  if (transcript.messages.length === 0) return null;
  const count = transcript.messages.length;
  return (
    <Card>
      <section aria-labelledby="website-chat-heading">
        <div className="border-b border-slate-200 px-5 py-4">
          <h2
            id="website-chat-heading"
            className="text-base font-semibold text-slate-900"
          >
            Website chat
          </h2>
          <p className="mt-0.5 text-xs text-slate-500">
            {transcript.started_at &&
              `Started ${formatDateTime(transcript.started_at)} · `}
            {count} {count === 1 ? "message" : "messages"}
          </p>
        </div>
        <ol className="max-h-96 space-y-3 overflow-y-auto px-5 py-4">
          {transcript.messages.map((m, index) => (
            <li
              key={index}
              className={cx(
                "rounded-lg px-3 py-2 text-sm",
                m.role === "visitor"
                  ? "mr-8 bg-slate-100 text-slate-900"
                  : "ml-8 bg-brand-50 text-slate-800",
              )}
            >
              <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                {m.role === "visitor" ? "Visitor" : "Assistant"}
                <span className="ml-2 font-normal normal-case tracking-normal">
                  <time dateTime={m.created_at}>
                    {formatDateTime(m.created_at)}
                  </time>
                </span>
              </p>
              <p className="mt-1 whitespace-pre-line break-words">{m.content}</p>
            </li>
          ))}
        </ol>
      </section>
    </Card>
  );
}
