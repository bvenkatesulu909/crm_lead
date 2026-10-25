"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";

import { buttonClass, cx } from "@/components/ui";
import {
  CHAT_MESSAGE_MAX,
  type ChatAnswer,
  type ChatProblem,
  chatErrorText,
  checkVisitorMessage,
} from "@/lib/public-chat";

type Line = { role: "visitor" | "assistant"; text: string };

const GREETING =
  "Hello! I can help you find a home. Tell me what you are looking for - the type of " +
  "property, your budget and the area - and leave your name and phone number so an advisor " +
  "can call you.";

/**
 * The website chat for home buyers (ADR 0013). Talks only to our own /api/public-chat route;
 * the conversation token lives in an httpOnly cookie this code can't read. Every answer is
 * shown as plain text (React escapes it), so a reply can never load images or links.
 */
export function PublicChat({
  privacyUrl,
  endpoint = "/api/public-chat",
}: {
  privacyUrl?: string;
  endpoint?: string;
}) {
  const [lines, setLines] = useState<Line[]>([]);
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const [saved, setSaved] = useState(false);
  const end = useRef<HTMLLIElement>(null);

  useEffect(() => {
    end.current?.scrollIntoView?.({ block: "end" });
  }, [lines]);

  async function send(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const problem = checkVisitorMessage(text);
    if (problem) {
      setError(problem);
      return;
    }
    // Bots fill every field; people never see this one.
    const website = String(
      new FormData(event.currentTarget).get("website") ?? "",
    );
    const message = text.trim();
    setSending(true);
    setError(null);
    try {
      const response = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message, website }),
      });
      const body = (await response.json().catch(() => ({}))) as ChatAnswer &
        ChatProblem;
      if (!response.ok) {
        setError(chatErrorText(response.status, body.code, body.detail));
        return;
      }
      setLines((current) => [
        ...current,
        { role: "visitor", text: message },
        { role: "assistant", text: body.reply },
      ]);
      setText("");
      if (body.lead_saved) setSaved(true);
    } catch {
      setError(chatErrorText(503));
    } finally {
      setSending(false);
    }
  }

  return (
    <div className="flex h-full flex-col">
      <p className="rounded-md bg-slate-100 px-4 py-3 text-xs text-slate-600">
        Your messages and the details you share are stored to answer your
        enquiry.
        {privacyUrl && (
          <>
            {" "}
            <a
              href={privacyUrl}
              className="font-medium text-brand-700 underline"
              target="_blank"
              rel="noopener noreferrer"
            >
              Read our privacy notice
            </a>
            .
          </>
        )}
      </p>

      <ol
        aria-label="Conversation"
        className="my-4 flex-1 space-y-3 overflow-y-auto"
      >
        <Bubble role="assistant" text={GREETING} />
        {lines.map((line, index) => (
          <Bubble key={index} role={line.role} text={line.text} />
        ))}
        <li ref={end} aria-hidden="true" />
      </ol>

      {saved && (
        <p
          role="status"
          className="mb-3 rounded-md border border-green-200 bg-green-50 px-4 py-2 text-sm text-green-800"
        >
          Your details were passed on to our team. An advisor will call you.
        </p>
      )}
      {error && (
        <p
          role="alert"
          className="mb-3 rounded-md border border-red-200 bg-red-50 px-4 py-2 text-sm text-red-800"
        >
          {error}
        </p>
      )}

      <form onSubmit={send} className="flex items-end gap-2" noValidate>
        {/* Honeypot: hidden from people (and screen readers); bots that fill it are refused. */}
        <div
          aria-hidden="true"
          className="absolute -left-[9999px] h-px w-px overflow-hidden"
        >
          <label>
            Website
            <input
              type="text"
              name="website"
              tabIndex={-1}
              autoComplete="off"
              defaultValue=""
            />
          </label>
        </div>
        <label className="flex-1">
          <span className="sr-only">Your message</span>
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                e.currentTarget.form?.requestSubmit();
              }
            }}
            rows={2}
            maxLength={CHAT_MESSAGE_MAX}
            placeholder="Type your message…"
            className="block w-full resize-none rounded-md border border-slate-300 px-3 py-2 text-sm shadow-sm focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/30"
          />
        </label>
        <button type="submit" className={buttonClass()} disabled={sending}>
          {sending ? "Sending…" : "Send"}
        </button>
      </form>
    </div>
  );
}

function Bubble({ role, text }: Line) {
  return (
    <li
      className={cx(
        "max-w-[85%] rounded-lg px-3 py-2 text-sm whitespace-pre-line break-words",
        role === "visitor"
          ? "ml-auto bg-brand-600 text-white"
          : "mr-auto bg-white text-slate-900 ring-1 ring-slate-200",
      )}
    >
      <span className="sr-only">
        {role === "visitor" ? "You: " : "Assistant: "}
      </span>
      {text}
    </li>
  );
}
