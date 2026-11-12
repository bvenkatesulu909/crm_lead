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

// --- Languages (ADR 0027) ---------------------------------------------------------------------

/** The three languages of the chat. The code is what the API accepts - a fixed list. */
export const CHAT_LANGUAGES = ["en", "hi", "te"] as const;
export type ChatLanguage = (typeof CHAT_LANGUAGES)[number];

export const isChatLanguage = (value: unknown): value is ChatLanguage =>
  typeof value === "string" &&
  (CHAT_LANGUAGES as readonly string[]).includes(value);

/** Each language written in itself, so a visitor can find theirs. */
export const CHAT_LANGUAGE_NAMES: Record<ChatLanguage, string> = {
  en: "English",
  hi: "हिन्दी",
  te: "తెలుగు",
};

/** The language tag the browser's speech recognition and voices are asked for. */
export const SPEECH_LANG: Record<ChatLanguage, string> = {
  en: "en-IN",
  hi: "hi-IN",
  te: "te-IN",
};

/** The chat language that matches the browser's own, or English. */
export function pickLanguage(
  preferred: readonly string[] | undefined,
): ChatLanguage {
  for (const tag of preferred ?? []) {
    const base = tag.toLowerCase().split("-")[0];
    if (isChatLanguage(base)) return base;
  }
  return "en";
}

/** Everything the visitor reads on the chat page, in each language. */
export type ChatText = {
  greeting: string;
  placeholder: string;
  yourMessage: string;
  send: string;
  sending: string;
  language: string;
  speak: string;
  listening: string;
  micFailed: string;
  readAloud: string;
  speechNotice: string;
  saved: string;
};

export const CHAT_TEXT: Record<ChatLanguage, ChatText> = {
  en: {
    greeting:
      "Hello! I can help you find a home. Tell me what you are looking for - the type of " +
      "property, your budget and the area - and leave your name and phone number so an advisor " +
      "can call you.",
    placeholder: "Type your message…",
    yourMessage: "Your message",
    send: "Send",
    sending: "Sending…",
    language: "Language",
    speak: "Speak",
    listening: "Listening… tap to stop",
    micFailed: "Could not hear you. Please try again or type your message.",
    readAloud: "Read replies aloud",
    speechNotice:
      "Speaking uses your browser's speech service, which may send your voice to its provider. " +
      "We never receive your audio - only the words that appear in the message box.",
    saved: "Your details were passed on to our team. An advisor will call you.",
  },
  hi: {
    greeting:
      "नमस्ते! मैं आपको घर ढूँढने में मदद कर सकता हूँ। बताइए आप किस तरह की प्रॉपर्टी, कितने बजट में " +
      "और किस इलाके में चाहते हैं, और अपना नाम व फ़ोन नंबर दीजिए ताकि हमारे सलाहकार आपको कॉल कर सकें।",
    placeholder: "अपना संदेश लिखें…",
    yourMessage: "आपका संदेश",
    send: "भेजें",
    sending: "भेज रहे हैं…",
    language: "भाषा",
    speak: "बोलें",
    listening: "सुन रहे हैं… रोकने के लिए दबाएँ",
    micFailed:
      "आपकी आवाज़ सुनाई नहीं दी। कृपया दोबारा कोशिश करें या संदेश लिखें।",
    readAloud: "जवाब बोलकर सुनाएँ",
    speechNotice:
      "बोलने के लिए आपके ब्राउज़र की स्पीच सेवा इस्तेमाल होती है, जो आपकी आवाज़ अपने प्रदाता को भेज सकती है। " +
      "हमें आपकी आवाज़ नहीं मिलती - केवल संदेश बॉक्स में दिखने वाले शब्द मिलते हैं।",
    saved: "आपकी जानकारी हमारी टीम को भेज दी गई है। एक सलाहकार आपको कॉल करेगा।",
  },
  te: {
    greeting:
      "నమస్కారం! ఇల్లు వెతకడంలో నేను మీకు సహాయం చేయగలను. మీకు ఏ రకమైన ఆస్తి, ఎంత బడ్జెట్‌లో, " +
      "ఏ ప్రాంతంలో కావాలో చెప్పండి, మరియు మా సలహాదారు మీకు కాల్ చేయడానికి మీ పేరు, ఫోన్ నంబర్ ఇవ్వండి.",
    placeholder: "మీ సందేశం రాయండి…",
    yourMessage: "మీ సందేశం",
    send: "పంపండి",
    sending: "పంపుతున్నాము…",
    language: "భాష",
    speak: "మాట్లాడండి",
    listening: "వింటున్నాము… ఆపడానికి నొక్కండి",
    micFailed:
      "మీ గొంతు వినిపించలేదు. దయచేసి మళ్లీ ప్రయత్నించండి లేదా సందేశం రాయండి.",
    readAloud: "సమాధానాలను చదివి వినిపించండి",
    speechNotice:
      "మాట్లాడటానికి మీ బ్రౌజర్ స్పీచ్ సేవ వాడబడుతుంది, అది మీ గొంతును దాని ప్రొవైడర్‌కు పంపవచ్చు. " +
      "మాకు మీ ఆడియో అందదు - సందేశ పెట్టెలో కనిపించే పదాలు మాత్రమే అందుతాయి.",
    saved:
      "మీ వివరాలు మా బృందానికి పంపబడ్డాయి. ఒక సలహాదారు మీకు కాల్ చేస్తారు.",
  },
};
