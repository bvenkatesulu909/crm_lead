"use client";

import { useEffect, useRef, useState, useSyncExternalStore } from "react";

import { AssistantProposals } from "@/components/approval-views";
import { Card, buttonClass } from "@/components/ui";
import {
  StreamError,
  askInConversation,
  errorMessage,
  startConversation,
  type StreamDone,
  type StreamEvent,
} from "@/lib/assistant-stream";
import {
  STATE_TEXT,
  chooseEngine,
  privacyText,
  unavailableText,
  type Choice,
  type VoiceStatus,
} from "@/lib/voice/choose";
import {
  VoiceConversation,
  type Listener,
  type Speaker,
  type VoiceState,
  type VoiceTurn,
} from "@/lib/voice/conversation";
import {
  BrowserListener,
  BrowserSpeaker,
  ScriptListener,
  ScriptSpeaker,
  ServerListener,
  ServerSpeaker,
  VoiceEngineError,
  browserCanListen,
  browserCanSpeak,
  canRecord,
  openMicrophone,
  scriptEngineOn,
  watchForBargeIn,
} from "@/lib/voice/engines";

const VOICE_ERRORS: Record<string, string> = {
  mic_blocked:
    "The microphone is blocked. Allow it for this site in the browser (and in Windows privacy settings), then try again.",
  mic_unavailable: "No microphone was found, or another app is using it.",
  cannot_listen:
    "This browser could not start listening. Please type your question.",
  listen_network:
    "The browser's speech service could not be reached. Please try again.",
  voice_off: "Voice is switched off for your organisation.",
  voice_budget_reached:
    "Voice has used this month's minutes. An administrator can help.",
  voice_unavailable:
    "The speech service is not available right now. Please type your question.",
};

const noSubscription = () => () => undefined;

type Engines = {
  listener: Listener;
  speaker: Speaker;
  stream: MediaStream | null;
};

async function buildEngines(choice: Choice): Promise<Engines> {
  if (choice.kind === "script")
    return {
      listener: new ScriptListener(),
      speaker: new ScriptSpeaker(),
      stream: null,
    };
  if (choice.kind === "server") {
    const stream = await openMicrophone();
    return {
      listener: new ServerListener(stream),
      speaker: new ServerSpeaker(),
      stream,
    };
  }
  return {
    listener: new BrowserListener(),
    speaker: new BrowserSpeaker(),
    stream: null,
  };
}

/**
 * A remembered conversation with the staff assistant (ADR 0023): type, or press one button and
 * talk. Answers arrive sentence by sentence and are spoken as they come. Everything shown is plain
 * text; changes the assistant proposes wait for a manager's approval.
 */
export function AssistantConversation({
  voice,
}: {
  voice: VoiceStatus | null;
}) {
  const [turns, setTurns] = useState<VoiceTurn[]>([]);
  const [state, setState] = useState<VoiceState>("idle");
  const [error, setError] = useState<string | null>(null);
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const [agreed, setAgreed] = useState(false);
  const [bargeIn, setBargeIn] = useState(false);
  const conversationId = useRef<string | null>(null);
  const loop = useRef<VoiceConversation | null>(null);
  const engines = useRef<Engines | null>(null);

  // What this browser can do is only known in the browser: on the server nothing is offered yet.
  const inBrowser = useSyncExternalStore(
    noSubscription,
    () => true,
    () => false,
  );
  const choice: Choice | null = inBrowser
    ? chooseEngine(voice, {
        canListen: browserCanListen(),
        canSpeak: browserCanSpeak(),
        canRecord: canRecord(),
        script: scriptEngineOn(),
      })
    : null;

  useEffect(() => () => endVoice(), []);

  // While the assistant speaks, a person who starts talking can cut it off (needs headphones on
  // most laptops: the speakers would otherwise trigger it).
  useEffect(() => {
    const stream = engines.current?.stream;
    if (!bargeIn || state !== "speaking" || !stream) return;
    return watchForBargeIn(stream, () => loop.current?.interrupt());
  }, [bargeIn, state]);

  async function conversation(): Promise<string> {
    conversationId.current ??= await startConversation();
    return conversationId.current;
  }

  async function ask(
    question: string,
    mode: "text" | "voice",
    onEvent: (event: StreamEvent) => void,
  ): Promise<StreamDone> {
    const id = await conversation();
    try {
      return await askInConversation(id, question, mode, onEvent);
    } catch (problem) {
      // A conversation the server cleaned up: the next question starts a new one.
      if (
        problem instanceof StreamError &&
        problem.code === "conversation_not_found"
      )
        conversationId.current = null;
      throw problem;
    }
  }

  function showError(code: string, detail?: string) {
    setError(
      VOICE_ERRORS[code] ??
        (code === "nothing_heard"
          ? (detail ?? null)
          : errorMessage(code, detail)),
    );
  }

  async function sendTyped() {
    const question = typed.trim();
    if (!question || busy) return;
    setBusy(true);
    setError(null);
    setTyped("");
    const answer: VoiceTurn = { role: "assistant", text: "" };
    const before: VoiceTurn[] = [
      ...turns,
      { role: "user", text: question, final: true },
    ];
    setTurns([...before, answer]);
    try {
      const done = await ask(question, "text", (event) => {
        if (event.type === "sentence") {
          answer.text = answer.text
            ? `${answer.text} ${event.text}`
            : event.text;
          setTurns([...before, { ...answer }]);
        }
      });
      setTurns([
        ...before,
        {
          role: "assistant",
          text: done.answer,
          proposals: done.proposals,
          final: true,
        },
      ]);
    } catch (problem) {
      setTurns(before);
      setTyped(question);
      const code =
        problem instanceof StreamError ? problem.code : "assistant_unavailable";
      showError(
        code,
        problem instanceof StreamError ? problem.detail : undefined,
      );
    } finally {
      setBusy(false);
    }
  }

  async function startVoice() {
    if (!choice || choice.kind === "none") return;
    setError(null);
    try {
      engines.current = await buildEngines(choice);
    } catch (problem) {
      showError(
        problem instanceof VoiceEngineError ? problem.code : "mic_unavailable",
      );
      return;
    }
    const { listener, speaker } = engines.current;
    let voiceTurnsSet = new Set<VoiceTurn>();
    const instance = new VoiceConversation(
      listener,
      speaker,
      (question, onEvent) => ask(question, "voice", onEvent),
      {
        onState: setState,
        onTurns: (voiceTurns) =>
          setTurns((current) => {
            // Typed turns before this voice session stay; the session's own turns follow.
            const typedBefore = current.filter((t) => !voiceTurnsSet.has(t));
            const next = [...typedBefore, ...voiceTurns];
            voiceTurnsSet = new Set(voiceTurns);
            return next;
          }),
        onError: showError,
      },
    );
    loop.current = instance;
    setBusy(true);
    try {
      await instance.start();
    } catch (problem) {
      showError(
        problem instanceof VoiceEngineError
          ? problem.code
          : "voice_unavailable",
      );
    } finally {
      setBusy(false);
      endVoice();
    }
  }

  function endVoice() {
    loop.current?.stop();
    loop.current = null;
    engines.current?.stream?.getTracks().forEach((track) => track.stop());
    engines.current = null;
  }

  function newConversation() {
    endVoice();
    conversationId.current = null;
    setTurns([]);
    setError(null);
  }

  const voiceOn = state !== "idle";
  const offered = choice && choice.kind !== "none";
  const reason =
    choice?.kind === "none" ? unavailableText(choice.reason) : null;

  return (
    <Card className="p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-base font-semibold text-slate-900">
          Talk with the assistant
        </h2>
        {turns.length > 0 && (
          <button
            type="button"
            onClick={newConversation}
            className={buttonClass("secondary")}
          >
            New conversation
          </button>
        )}
      </div>
      <p className="mt-1 text-sm text-slate-600">
        It remembers this conversation for a day, so you can ask follow-up
        questions.
      </p>

      <ol aria-label="Conversation" className="mt-4 space-y-3">
        {turns.map((turn, index) => (
          <li
            key={index}
            className={
              turn.role === "user"
                ? "ml-8 rounded-md bg-brand-50 px-3 py-2 text-sm text-slate-900"
                : "mr-8 rounded-md bg-slate-50 px-3 py-2 text-sm text-slate-800"
            }
          >
            <span className="sr-only">
              {turn.role === "user" ? "You: " : "Assistant: "}
            </span>
            <span className="whitespace-pre-line">{turn.text || "…"}</span>
            {turn.proposals && (
              <AssistantProposals proposals={turn.proposals} />
            )}
          </li>
        ))}
      </ol>

      {error && (
        <p
          role="alert"
          className="mt-3 rounded-md bg-red-50 px-3 py-2 text-sm text-red-800"
        >
          {error}
        </p>
      )}

      <form
        className="mt-4 flex flex-wrap gap-2"
        onSubmit={(event) => {
          event.preventDefault();
          void sendTyped();
        }}
      >
        <label htmlFor="conversation-question" className="sr-only">
          Your question
        </label>
        <input
          id="conversation-question"
          value={typed}
          maxLength={2000}
          disabled={voiceOn}
          onChange={(event) => setTyped(event.target.value)}
          placeholder="Type a question, or start a voice conversation"
          className="min-w-0 flex-1 rounded-md border-0 px-3 py-2 text-sm ring-1 ring-inset ring-slate-300 focus:ring-2 focus:ring-brand-600"
        />
        <button
          type="submit"
          disabled={busy || !typed.trim()}
          className={buttonClass("primary")}
        >
          Send
        </button>
      </form>

      <div className="mt-4 border-t border-slate-200 pt-4">
        {voiceOn ? (
          <div className="flex flex-wrap items-center gap-3">
            <span
              aria-live="polite"
              className="text-sm font-medium text-brand-800"
            >
              {STATE_TEXT[state]}
            </span>
            {state === "speaking" && (
              <button
                type="button"
                onClick={() => loop.current?.interrupt()}
                className={buttonClass("secondary")}
              >
                Skip
              </button>
            )}
            <button
              type="button"
              onClick={endVoice}
              className={buttonClass("danger")}
            >
              Stop voice conversation
            </button>
          </div>
        ) : offered ? (
          agreed ? (
            <button
              type="button"
              disabled={busy}
              onClick={() => void startVoice()}
              className={buttonClass("primary")}
            >
              Start voice conversation
            </button>
          ) : (
            <div className="rounded-md bg-slate-50 p-3 text-sm text-slate-700">
              <p>{privacyText(choice.kind)}</p>
              <button
                type="button"
                onClick={() => {
                  setAgreed(true);
                  void startVoice();
                }}
                className={`mt-2 ${buttonClass("primary")}`}
              >
                Allow microphone and start
              </button>
            </div>
          )
        ) : (
          reason && <p className="text-sm text-slate-600">{reason}</p>
        )}
        {offered && choice.kind === "server" && (
          <label className="mt-3 flex items-center gap-2 text-sm text-slate-700">
            <input
              type="checkbox"
              checked={bargeIn}
              onChange={(event) => setBargeIn(event.target.checked)}
            />
            Interrupt the assistant by speaking (best with headphones)
          </label>
        )}
        <p className="mt-3 text-xs text-slate-500">
          Advice only. Nothing is sent to a customer, and changes the assistant
          proposes wait for a manager&apos;s approval. Voice cannot approve
          anything.
        </p>
      </div>
    </Card>
  );
}
