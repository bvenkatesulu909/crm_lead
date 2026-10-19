import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { Card, EmptyState, ErrorAlert, buttonClass, cx } from "@/components/ui";
import { ApiError, toErrorInfo } from "@/lib/api-error";
import type {
  AssistantAction,
  AssistantConversation,
  AssistantConversationSummary,
} from "@/lib/api-types";
import { formatDateTime } from "@/lib/format";
import { initialFormState } from "@/lib/form-state";
import { apiFetch } from "@/lib/server/api";

import { decideAction, sendMessage } from "./actions";
import { ChatForm } from "./chat-form";

export const metadata: Metadata = { title: "Assistant" };

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/**
 * The AI assistant for customers. It answers from the customer's OWN data only (the backend
 * enforces that), and can hand a question over to a person - after the customer confirms.
 */
export default async function AssistantPage({
  searchParams,
}: PageProps<"/portal/assistant">) {
  const params = await searchParams;
  const id = typeof params.c === "string" ? params.c : null;
  if (id !== null && !UUID.test(id)) notFound();

  let available: boolean;
  let history: AssistantConversationSummary[];
  let conversation: AssistantConversation | null = null;
  try {
    [{ available }, history, conversation] = await Promise.all([
      apiFetch<{ available: boolean }>("/portal/assistant/status"),
      apiFetch<AssistantConversationSummary[]>(
        "/portal/assistant/conversations",
      ),
      id
        ? apiFetch<AssistantConversation>(
            `/portal/assistant/conversations/${id}`,
          )
        : Promise.resolve(null),
    ]);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) notFound();
    return (
      <ErrorAlert
        title="The assistant could not be loaded"
        error={toErrorInfo(error)}
      />
    );
  }

  return (
    <>
      <nav aria-label="Breadcrumb" className="mb-4 text-sm">
        <Link href="/portal" className="font-medium text-brand-700 hover:underline">← Portal home</Link>
      </nav>
      <h1 className="text-2xl font-semibold tracking-tight text-slate-900">Assistant</h1>
      <p className="mt-1 mb-6 text-sm text-slate-600">
        You are chatting with an AI assistant. It only sees your company&apos;s data, it can make mistakes,
        and for anything a person must decide it prepares a support ticket for you to confirm.
      </p>

      {!available ? (
        <Card>
          <EmptyState
            title="The assistant is not available right now"
            description="You can still open a support ticket and our team will help."
            action={<Link href="/portal/tickets/new" className={buttonClass("primary")}>Open a ticket</Link>}
          />
        </Card>
      ) : (
        <div className="grid gap-6 lg:grid-cols-[1fr_16rem]">
          <Card className="flex min-h-[28rem] flex-col">
            <ol aria-label="Conversation" aria-live="polite" className="flex-1 space-y-4 p-5">
              {!conversation && (
                <li className="text-sm text-slate-600">
                  Ask for example: “Where is my latest order?”, “Which invoices are still open?” or
                  “What&apos;s happening with my ticket?”
                </li>
              )}
              {conversation?.messages.map((m) => (
                <li key={m.id} className={cx("max-w-[85%] rounded-lg px-4 py-3 text-sm", m.role === "user" ? "ml-auto bg-brand-600 text-white" : "bg-slate-100 text-slate-900")}>
                  <p className="sr-only">{m.role === "user" ? "You:" : "Assistant:"}</p>
                  <p className="whitespace-pre-line">{m.content}</p>
                  <time dateTime={m.created_at} className={cx("mt-1 block text-[11px]", m.role === "user" ? "text-brand-100" : "text-slate-500")}>
                    {formatDateTime(m.created_at)}
                  </time>
                </li>
              ))}
              {conversation?.actions.map((a) => <ActionCard key={a.id} action={a} />)}
            </ol>
            <ChatForm action={sendMessage.bind(null, conversation?.id ?? null)} initialState={initialFormState} />
          </Card>
          <aside aria-label="Previous conversations">
            <Link href="/portal/assistant" className={cx(buttonClass("secondary"), "mb-3 w-full")}>New conversation</Link>
            <ul className="space-y-1 text-sm">
              {history.map((h) => (
                <li key={h.id}>
                  <Link href={`/portal/assistant?c=${h.id}`} aria-current={h.id === conversation?.id ? "page" : undefined}
                    className={cx("block truncate rounded px-2 py-1.5 hover:bg-slate-100", h.id === conversation?.id && "bg-slate-100 font-medium")}>
                    {h.title}
                  </Link>
                </li>
              ))}
            </ul>
          </aside>
        </div>
      )}
    </>
  ); // prettier-ignore
}

/** A ticket the assistant PREPARED. Only the customer's click creates it. */
function ActionCard({ action }: { action: AssistantAction }) {
  return (
    <li role="group" aria-label="Prepared support ticket" className="rounded-lg border border-amber-300 bg-amber-50 p-4 text-sm">
      <p className="font-semibold text-amber-950">
        {action.status === "pending" && "Hand over to our support team?"}
        {action.status === "confirmed" && `Ticket T-${String(action.ticket_number).padStart(4, "0")} created`}
        {action.status === "cancelled" && "Not sent"}
      </p>
      <dl className="mt-2 space-y-1 text-amber-950">
        <div><dt className="inline font-medium">Account: </dt><dd className="inline">{action.account_name}</dd></div>
        <div><dt className="inline font-medium">Subject: </dt><dd className="inline">{action.subject}</dd></div>
        <div><dt className="font-medium">Message:</dt><dd className="whitespace-pre-line">{action.description}</dd></div>
      </dl>
      {action.status === "pending" && (
        <div className="mt-3 flex gap-2">
          <form action={decideAction.bind(null, action.id, "confirm")}>
            <button type="submit" className={buttonClass("primary")}>Create ticket</button>
          </form>
          <form action={decideAction.bind(null, action.id, "cancel")}>
            <button type="submit" className={buttonClass("secondary")}>Don&apos;t send</button>
          </form>
        </div>
      )}
    </li>
  ); // prettier-ignore
}
