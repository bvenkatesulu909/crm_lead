/**
 * Rules of the public website chat (ADR 0013) shared by the `/chat` page and its route handler.
 * Nothing here is secret: the server key and the conversation token stay on the Next.js server.
 */

/** The API's guardrails refuse anything longer, so the page says so before sending. */
export const CHAT_MESSAGE_MAX = 2000;

export type ChatAnswer = { reply: string; lead_saved: boolean };
export type ChatProblem = { detail?: string; code?: string };

/** An error text for the visitor, or null when the message can be sent. */
export function checkVisitorMessage(text: string): string | null {
  const trimmed = text.trim();
  if (!trimmed) return "Please type a message first.";
  if (trimmed.length > CHAT_MESSAGE_MAX)
    return "Please keep your message under 2,000 characters.";
  return null;
}

/** What the visitor reads when the chat couldn't answer. */
export function chatErrorText(
  status: number,
  code?: string,
  detail?: string,
): string {
  if (status === 429 && code === "public_chat_busy")
    return "The chat is very busy today. Please try again tomorrow or call us.";
  if (status === 429)
    return "You have sent many messages. Please wait a while and try again.";
  if (status === 404 || status === 503)
    return "The chat is not available right now. Please call us or try again later.";
  // The guardrails explain themselves (e.g. "please don't share card numbers here").
  if (status === 422 && code === "message_refused" && detail) return detail;
  if (status === 422)
    return "This message could not be sent. Please rephrase it.";
  return "Something went wrong. Please try again.";
}
