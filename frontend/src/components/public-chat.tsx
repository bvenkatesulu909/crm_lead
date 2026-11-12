"use client";

import {
  useEffect,
  useRef,
  useState,
  useSyncExternalStore,
  type FormEvent,
} from "react";

import { buttonClass, cx } from "@/components/ui";
import {
  CHAT_LANGUAGES,
  CHAT_LANGUAGE_NAMES,
  CHAT_MESSAGE_MAX,
  CHAT_TEXT,
  SPEECH_LANG,
  type ChatAnswer,
  type ChatLanguage,
  type ChatProblem,
  chatErrorText,
  checkVisitorMessage,
  pickLanguage,
} from "@/lib/public-chat";
import {
  createRecognition,
  speechRecognitionAvailable,
  type SpeechRecognitionLike,
} from "@/lib/speech";

type Line = { role: "visitor" | "assistant"; text: string };

/**
 * The website chat for home buyers (ADR 0013). Talks only to our own /api/public-chat route;
 * the conversation token lives in an httpOnly cookie this code can't read. Every answer is
 * shown as plain text (React escapes it), so a reply can never load images or links.
 *
 * Hindi and Telugu (ADR 0027): the visitor picks a language; the words on this page, the
 * answers and the language written on the lead follow it. Speaking and hearing use the
 * browser's own speech - this code never receives audio, only the words it recognised.
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
  // null until the visitor chooses: then the browser's own language, if it is one of ours.
  const [choice, setChoice] = useState<ChatLanguage | null>(null);
  const browserLanguage = useSyncExternalStore(
    () => () => {},
    () => pickLanguage(navigator.languages),
    () => "en" as ChatLanguage,
  );
  const language = choice ?? browserLanguage;
  const words = CHAT_TEXT[language];
  const [listening, setListening] = useState(false);
  const [readAloud, setReadAloud] = useState(false);
  const recognition = useRef<SpeechRecognitionLike | null>(null);
  const canListen = useSyncExternalStore(
    () => () => {},
    speechRecognitionAvailable,
    () => false,
  );
  const canSpeak = useSyncExternalStore(
    () => () => {},
    () => "speechSynthesis" in window,
    () => false,
  );

  useEffect(() => {
    end.current?.scrollIntoView?.({ block: "end" });
  }, [lines]);

  // Leaving the page stops the microphone and any voice that is still talking.
  useEffect(
    () => () => {
      recognition.current?.stop();
      if ("speechSynthesis" in window) window.speechSynthesis.cancel();
    },
    [],
  );

  function chooseLanguage(next: ChatLanguage) {
    recognition.current?.stop();
    if ("speechSynthesis" in window) window.speechSynthesis.cancel();
    setChoice(next);
  }

  function toggleReadAloud(on: boolean) {
    setReadAloud(on);
    if (!on && "speechSynthesis" in window) window.speechSynthesis.cancel();
  }

  function speak(reply: string) {
    if (!("speechSynthesis" in window)) return;
    const utterance = new SpeechSynthesisUtterance(reply);
    utterance.lang = SPEECH_LANG[language];
    window.speechSynthesis.cancel();
    window.speechSynthesis.speak(utterance);
  }

  function toggleListening() {
    if (listening) {
      recognition.current?.stop();
      return;
    }
    const heard = createRecognition();
    if (!heard) return;
    const before = text.trim() ? `${text.trim()} ` : "";
    heard.lang = SPEECH_LANG[language];
    heard.continuous = false;
    heard.interimResults = true;
    heard.onresult = (event) => {
      let said = "";
      for (let i = 0; i < event.results.length; i += 1)
        said += event.results[i][0].transcript;
      // Only the words land in the box: the visitor reads them and presses Send.
      setText((before + said).slice(0, CHAT_MESSAGE_MAX));
    };
    heard.onend = () => setListening(false);
    heard.onerror = () => {
      setListening(false);
      setError(words.micFailed);
    };
    recognition.current = heard;
    setError(null);
    setListening(true);
    heard.start();
  }

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
        body: JSON.stringify({ message, website, language }),
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
      if (readAloud) speak(body.reply);
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

      <div
        role="group"
        aria-label={words.language}
        className="mt-3 flex flex-wrap items-center gap-2"
      >
        {CHAT_LANGUAGES.map((code) => (
          <button
            key={code}
            type="button"
            aria-pressed={code === language}
            onClick={() => chooseLanguage(code)}
            className={cx(
              "rounded-full px-3 py-1 text-sm font-medium ring-1 ring-inset",
              code === language
                ? "bg-brand-600 text-white ring-brand-600"
                : "bg-white text-slate-700 ring-slate-300 hover:bg-slate-50",
            )}
          >
            {CHAT_LANGUAGE_NAMES[code]}
          </button>
        ))}
        {canSpeak && (
          <label className="ml-auto flex items-center gap-2 text-sm text-slate-700">
            <input
              type="checkbox"
              checked={readAloud}
              onChange={(e) => toggleReadAloud(e.target.checked)}
            />
            {words.readAloud}
          </label>
        )}
      </div>

      <ol
        aria-label="Conversation"
        className="my-4 flex-1 space-y-3 overflow-y-auto"
      >
        <Bubble role="assistant" text={words.greeting} />
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
          {words.saved}
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
          <span className="sr-only">{words.yourMessage}</span>
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
            placeholder={words.placeholder}
            className="block w-full resize-none rounded-md border border-slate-300 px-3 py-2 text-sm shadow-sm focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/30"
          />
        </label>
        {canListen && (
          <button
            type="button"
            onClick={toggleListening}
            aria-pressed={listening}
            className={buttonClass("secondary")}
          >
            {listening ? words.listening : words.speak}
          </button>
        )}
        <button type="submit" className={buttonClass()} disabled={sending}>
          {sending ? words.sending : words.send}
        </button>
      </form>
      {canListen && (
        <p className="mt-2 text-xs text-slate-500">{words.speechNotice}</p>
      )}
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
