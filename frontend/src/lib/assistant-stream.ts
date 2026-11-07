/**
 * Reading the staff assistant's streamed answer in the browser (ADR 0023).
 *
 * The answer arrives as Server-Sent Events through our own route handler (the token never reaches
 * the browser): `sentence` {text} - one cleaned sentence, `working` {} - tools are running, then
 * `done` {answer, links, proposals} or `error` {code, detail}.
 */

export type StreamProposal = {
  id: string;
  description: string;
  status: string;
  link: string;
};

export type StreamDone = {
  answer: string;
  ticket_id: string;
  links: string[];
  proposals: StreamProposal[];
};

export type StreamEvent =
  | { type: "sentence"; text: string }
  | { type: "working" }
  | { type: "done"; done: StreamDone }
  | { type: "error"; code: string; detail: string };

/** Turns the raw text of a stream into events; keeps an unfinished event for the next chunk. */
export class EventParser {
  private buffer = "";

  push(chunk: string): StreamEvent[] {
    this.buffer += chunk.replace(/\r\n/g, "\n");
    const events: StreamEvent[] = [];
    let end = this.buffer.indexOf("\n\n");
    while (end !== -1) {
      const block = this.buffer.slice(0, end);
      this.buffer = this.buffer.slice(end + 2);
      const event = parseBlock(block);
      if (event) events.push(event);
      end = this.buffer.indexOf("\n\n");
    }
    return events;
  }
}

function parseBlock(block: string): StreamEvent | null {
  let name = "message";
  const data: string[] = [];
  for (const line of block.split("\n")) {
    if (line.startsWith("event:")) name = line.slice(6).trim();
    else if (line.startsWith("data:")) data.push(line.slice(5).trim());
  }
  let payload: Record<string, unknown> = {};
  try {
    payload = data.length
      ? (JSON.parse(data.join("\n")) as Record<string, unknown>)
      : {};
  } catch {
    return null;
  }
  if (name === "sentence" && typeof payload.text === "string")
    return { type: "sentence", text: payload.text };
  if (name === "working") return { type: "working" };
  if (name === "done" && typeof payload.answer === "string")
    return {
      type: "done",
      done: {
        answer: payload.answer,
        ticket_id: String(payload.ticket_id ?? ""),
        links: Array.isArray(payload.links) ? payload.links.map(String) : [],
        proposals: Array.isArray(payload.proposals)
          ? (payload.proposals as StreamProposal[])
          : [],
      },
    };
  if (name === "error")
    return {
      type: "error",
      code: String(payload.code ?? "assistant_unavailable"),
      detail: String(payload.detail ?? "The assistant could not answer."),
    };
  return null;
}

/** Plain words for an error code the API or this page can give. */
export function errorMessage(code: string, detail?: string): string {
  switch (code) {
    case "agent_unavailable":
      return "The assistant is switched off for your organisation right now.";
    case "agent_budget_reached":
      return "The assistant has used this month's allowance. An administrator can raise it.";
    case "conversation_not_found":
      return "This conversation has ended. A new one has been started - please ask again.";
    case "conversation_full":
      return "This conversation is very long. Start a new one to continue.";
    case "assistant_unavailable":
      return "The assistant could not answer just now. Please try again.";
    case "not_signed_in":
      return "Your session has ended. Please sign in again.";
    default:
      return detail || "The assistant could not answer. Please try again.";
  }
}

export async function startConversation(): Promise<string> {
  const response = await fetch("/assistant/conversations", { method: "POST" });
  if (!response.ok)
    throw new StreamError(
      response.status === 401 ? "not_signed_in" : "start_failed",
    );
  const body = (await response.json()) as { id?: string };
  if (!body.id) throw new StreamError("start_failed");
  return body.id;
}

export class StreamError extends Error {
  constructor(
    public code: string,
    public detail = "",
  ) {
    super(code);
  }
}

/**
 * Asks one question and calls `onEvent` for every event as it arrives. Resolves with the final
 * `done`; rejects with a StreamError on any refusal (before or during the stream).
 */
export async function askInConversation(
  conversationId: string,
  question: string,
  mode: "text" | "voice",
  onEvent: (event: StreamEvent) => void,
  signal?: AbortSignal,
): Promise<StreamDone> {
  const response = await fetch(
    `/assistant/conversations/${conversationId}/turns`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, mode }),
      signal,
    },
  );
  if (!response.ok || !response.body) {
    const problem = (await response.json().catch(() => ({}))) as {
      code?: string;
      detail?: string;
    };
    const code =
      response.status === 401
        ? "not_signed_in"
        : (problem.code ?? "assistant_unavailable");
    throw new StreamError(code, problem.detail ?? "");
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  const parser = new EventParser();
  let done: StreamDone | null = null;
  for (;;) {
    const { value, done: finished } = await reader.read();
    const events = parser.push(
      finished
        ? decoder.decode() + "\n\n"
        : decoder.decode(value, { stream: true }),
    );
    for (const event of events) {
      if (event.type === "error")
        throw new StreamError(event.code, event.detail);
      if (event.type === "done") done = event.done;
      onEvent(event);
    }
    if (finished) break;
  }
  if (!done) throw new StreamError("assistant_unavailable");
  return done;
}
